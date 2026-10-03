"""
投掷物系统 - 核心模块

已修复的问题：
- 抛物线考虑空气阻力，初速度/质量/口径按投掷物类型配置
- 碰撞检测覆盖地面、墙壁、天花板，反射向量按 v' = v - 2(v·n)n 计算
- 弹性系数按表面配置，弹跳时施加摩擦力
- 生命周期：爆炸后销毁并移出场景，引信计时从落地开始（可配置）
- 引信支持定时触发（timer）与碰撞触发（impact）
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math

Vec3 = Tuple[float, float, float]


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3) -> Vec3:
    n = _length(a)
    if n <= 0.0:
        raise ValueError("方向向量不能为零向量")
    return (a[0] / n, a[1] / n, a[2] / n)


# 投掷物类型属性：质量、初速度、空气阻力系数、半径、引信
DEFAULT_PROJECTILES: Dict[str, Dict] = {
    "grenade": {
        "mass": 0.4, "initial_speed": 25.0, "drag": 0.02, "radius": 0.1,
        "fuse_time": 3.0, "fuse_mode": "timer", "fuse_starts_on": "land",
    },
    "flashbang": {
        "mass": 0.3, "initial_speed": 22.0, "drag": 0.03, "radius": 0.08,
        "fuse_time": 1.5, "fuse_mode": "timer", "fuse_starts_on": "throw",
    },
    "rock": {
        "mass": 2.0, "initial_speed": 15.0, "drag": 0.01, "radius": 0.15,
        "fuse_time": 0.0, "fuse_mode": "none", "fuse_starts_on": "throw",
    },
}

# 表面物理属性：弹性系数（restitution）与摩擦系数（friction）
DEFAULT_SURFACES: Dict[str, Dict] = {
    "concrete": {"restitution": 0.6, "friction": 0.3},
    "grass": {"restitution": 0.25, "friction": 0.8},
    "default": {"restitution": 0.5, "friction": 0.5},
}

DEFAULT_WORLD: Dict = {
    "bounds": {"x": (-100.0, 100.0), "y": (0.0, 100.0), "z": (-100.0, 100.0)},
    "surfaces": {"ground": "concrete", "ceiling": "concrete", "wall": "concrete"},
}

# 速度低于该值且贴地时视为静止（落地）
REST_SPEED = 1.0
# 引信触发后销毁前的状态驻留帧数由 lifecycle 管理
_VALID_FUSE_MODES = ("timer", "impact", "none")


@dataclass
class Config:
    """配置项"""
    pass


class ProjectileSystem:
    """投掷物系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.gravity = float(self.config.get("gravity", 9.81))

        self.projectile_types = {k: dict(v) for k, v in DEFAULT_PROJECTILES.items()}
        for name, override in self.config.get("projectiles", {}).items():
            base = self.projectile_types.get(name, {})
            base.update(override)
            self.projectile_types[name] = base

        self.surfaces = {k: dict(v) for k, v in DEFAULT_SURFACES.items()}
        for name, override in self.config.get("surfaces", {}).items():
            base = self.surfaces.get(name, {})
            base.update(override)
            self.surfaces[name] = base

        world = dict(DEFAULT_WORLD)
        world["bounds"] = {k: tuple(v) for k, v in DEFAULT_WORLD["bounds"].items()}
        world["surfaces"] = dict(DEFAULT_WORLD["surfaces"])
        for key, value in self.config.get("world", {}).items():
            if isinstance(value, dict) and isinstance(world.get(key), dict):
                world[key].update(value)
            else:
                world[key] = value
        self.world = world

        self._state: Dict = {}
        self._history: List = []
        self._projectiles: List[Dict] = []
        self._explosions: List[Dict] = []
        self._next_id = 1

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def active_projectiles(self) -> List[Dict]:
        """场景中仍存活的投掷物（已销毁的不在内）"""
        return list(self._projectiles)

    @property
    def explosions(self) -> List[Dict]:
        """已发生的爆炸事件记录"""
        return list(self._explosions)

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    def get_projectile_spec(self, projectile_type: str) -> Dict:
        if projectile_type not in self.projectile_types:
            raise KeyError(f"未知的投掷物类型: {projectile_type}")
        return self.projectile_types[projectile_type]

    def spawn(self, projectile_type: str, position: Vec3, direction: Vec3,
              speed: Optional[float] = None) -> Dict:
        """生成一个投掷物。初速度取类型配置，也可显式覆盖。"""
        spec = self.get_projectile_spec(projectile_type)
        direction = _normalize(direction)
        initial_speed = float(speed) if speed is not None else float(spec["initial_speed"])
        projectile = {
            "id": self._next_id,
            "type": projectile_type,
            "position": (float(position[0]), float(position[1]), float(position[2])),
            "velocity": _scale(direction, initial_speed),
            "radius": float(spec["radius"]),
            "state": "flying",
            "touched_ground": False,
            "fuse_elapsed": 0.0,
            "age": 0.0,
        }
        self._next_id += 1
        self._projectiles.append(projectile)
        return projectile

    # ------------------------------------------------------------------
    # 抛物线：重力 + 空气阻力（二次阻力），属性按投掷物类型
    # ------------------------------------------------------------------
    def calculate_trajectory(self, projectile_type: str, position: Vec3,
                             direction: Vec3, speed: Optional[float] = None,
                             dt: float = 0.02, max_time: float = 10.0) -> List[Vec3]:
        """计算弹道轨迹点序列（含空气阻力），落回地面时停止。"""
        spec = self.get_projectile_spec(projectile_type)
        mass = float(spec["mass"])
        drag = float(spec["drag"])
        radius = float(spec["radius"])
        initial_speed = float(speed) if speed is not None else float(spec["initial_speed"])

        pos = (float(position[0]), float(position[1]), float(position[2]))
        vel = _scale(_normalize(direction), initial_speed)

        points = [pos]
        t = 0.0
        while t < max_time:
            vel = self._integrate_velocity(vel, mass, drag, dt)
            pos = _add(pos, _scale(vel, dt))
            t += dt
            points.append(pos)
            if pos[1] <= radius and vel[1] < 0.0:
                break
        return points

    def _integrate_velocity(self, velocity: Vec3, mass: float, drag: float,
                            dt: float) -> Vec3:
        """半隐式欧拉积分：重力 + 二次空气阻力 F = -k|v|v，加速度按质量折算。"""
        speed = _length(velocity)
        drag_factor = drag * speed / max(mass, 1e-6)
        acc = (
            -drag_factor * velocity[0],
            -self.gravity - drag_factor * velocity[1],
            -drag_factor * velocity[2],
        )
        return _add(velocity, _scale(acc, dt))

    # ------------------------------------------------------------------
    # 弹跳物理：按表面弹性系数反射法向分量，摩擦力衰减切向分量
    # ------------------------------------------------------------------
    def bounce_physics(self, velocity: Vec3, normal: Vec3, surface: Dict) -> Vec3:
        """根据表面属性计算碰撞后的速度。

        法向分量按弹性系数反转，切向分量按摩擦系数衰减。
        """
        normal = _normalize(normal)
        restitution = float(surface.get("restitution", 0.5))
        friction = float(surface.get("friction", 0.5))

        vn = _scale(normal, _dot(velocity, normal))
        vt = (velocity[0] - vn[0], velocity[1] - vn[1], velocity[2] - vn[2])

        new_vn = _scale(vn, -restitution)
        new_vt = _scale(vt, max(0.0, 1.0 - friction))
        return _add(new_vn, new_vt)

    # ------------------------------------------------------------------
    # 碰撞检测：地面 / 墙壁 / 天花板全方向
    # ------------------------------------------------------------------
    def collide_and_bounce(self, projectile: Dict) -> Optional[Dict]:
        """检测与世界边界的碰撞并反弹，返回碰撞信息（无碰撞返回 None）。"""
        pos = list(projectile["position"])
        vel = projectile["velocity"]
        radius = projectile["radius"]
        bounds = self.world["bounds"]
        surface_map = self.world["surfaces"]

        last_collision = None
        for axis_index, axis_name in enumerate(("x", "y", "z")):
            lo, hi = bounds[axis_name]
            if pos[axis_index] - radius < lo:
                pos[axis_index] = lo + radius
                normal = [0.0, 0.0, 0.0]
                normal[axis_index] = 1.0
                kind = "ground" if axis_name == "y" else "wall"
            elif pos[axis_index] + radius > hi:
                pos[axis_index] = hi - radius
                normal = [0.0, 0.0, 0.0]
                normal[axis_index] = -1.0
                kind = "ceiling" if axis_name == "y" else "wall"
            else:
                continue

            surface_name = surface_map.get(kind, "default")
            surface = self.surfaces.get(surface_name, self.surfaces["default"])
            vel = self.bounce_physics(vel, tuple(normal), surface)
            last_collision = {
                "kind": kind,
                "normal": tuple(normal),
                "surface": surface_name,
                "position": tuple(pos),
            }

        projectile["position"] = (pos[0], pos[1], pos[2])
        projectile["velocity"] = vel
        if last_collision is not None and last_collision["kind"] == "ground":
            projectile["touched_ground"] = True
        return last_collision

    # ------------------------------------------------------------------
    # 引信计时器：支持定时（timer）与碰撞触发（impact）
    # ------------------------------------------------------------------
    def fuse_timer(self, projectile: Dict, dt: float) -> bool:
        """推进引信计时，返回本帧是否引爆。

        - timer 模式：按 fuse_starts_on 配置从扔出（throw）或落地静止（land）
          起算；落地前即使飞行时间超过引信时长也不会空中爆炸。
        - impact 模式：计时器不生效，由碰撞直接引爆。
        - none 模式：永不引爆。
        """
        spec = self.get_projectile_spec(projectile["type"])
        if spec.get("fuse_mode") != "timer":
            return False
        if projectile["state"] in ("exploded", "destroyed"):
            return False

        starts_on = spec.get("fuse_starts_on", "land")
        armed = starts_on == "throw" or projectile["state"] == "landed"
        if not armed:
            return False

        projectile["fuse_elapsed"] += dt
        return projectile["fuse_elapsed"] >= float(spec.get("fuse_time", 0.0))

    # ------------------------------------------------------------------
    # 生命周期：flying -> landed -> exploded -> destroyed
    # ------------------------------------------------------------------
    def projectile_lifecycle(self, projectile: Dict, dt: float) -> str:
        """推进单个投掷物的生命周期，返回当前状态。"""
        state = projectile["state"]
        if state == "destroyed":
            return state
        if state == "exploded":
            # 爆炸后销毁：移出场景，不再参与碰撞
            projectile["state"] = "destroyed"
            projectile["velocity"] = (0.0, 0.0, 0.0)
            if projectile in self._projectiles:
                self._projectiles.remove(projectile)
            return "destroyed"

        spec = self.get_projectile_spec(projectile["type"])
        impact_triggered = (
            spec.get("fuse_mode") == "impact" and projectile.pop("_impact_pending", False)
        )
        if impact_triggered or self.fuse_timer(projectile, dt):
            self._explode(projectile)
            return "exploded"

        # 落地静止判定：贴地且速度足够小
        if (projectile["touched_ground"]
                and projectile["position"][1] <= projectile["radius"] + 0.02
                and _length(projectile["velocity"]) < REST_SPEED):
            projectile["state"] = "landed"
            projectile["velocity"] = (0.0, 0.0, 0.0)

        return projectile["state"]

    def _explode(self, projectile: Dict) -> None:
        projectile["state"] = "exploded"
        event = {
            "id": projectile["id"],
            "type": projectile["type"],
            "position": projectile["position"],
            "age": projectile["age"],
        }
        self._explosions.append(event)
        self._history.append(("exploded", event))

    # ------------------------------------------------------------------
    # 帧更新
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """每帧更新：积分运动、碰撞反弹、引信与生命周期。"""
        for projectile in list(self._projectiles):
            if projectile["state"] in ("exploded", "destroyed", "landed"):
                # landed 的投掷物不再运动，但引信继续计时
                self.projectile_lifecycle(projectile, dt)
                continue

            spec = self.get_projectile_spec(projectile["type"])
            projectile["age"] += dt
            projectile["velocity"] = self._integrate_velocity(
                projectile["velocity"], float(spec["mass"]), float(spec["drag"]), dt)
            projectile["position"] = _add(
                projectile["position"], _scale(projectile["velocity"], dt))

            collision = self.collide_and_bounce(projectile)
            if collision is not None and spec.get("fuse_mode") == "impact":
                projectile["_impact_pending"] = True

            self.projectile_lifecycle(projectile, dt)

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []
        self._projectiles = []
        self._explosions = []
        self._next_id = 1
