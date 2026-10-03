"""
投掷物系统 - 核心模块

已修复的问题：
- calculate_trajectory(): 抛物线考虑空气阻力，初速度/重量等属性按投掷物类型配置
- collide_and_bounce(): 支持地面/墙壁/天花板全方向碰撞检测，正确计算反射向量
- bounce_physics(): 弹性系数按表面配置（水泥/草地等），并考虑摩擦力使投掷物停下
- projectile_lifecycle(): 爆炸后正确销毁并移出场景，引信从落地时开始计时
- fuse_timer(): 支持定时引信（落地后计时）与碰撞触发引信两种模式
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math

Vector3 = Tuple[float, float, float]

GRAVITY = 9.81
AIR_DENSITY = 1.225
REST_SPEED_THRESHOLD = 0.5


@dataclass
class Config:
    """配置项"""
    pass


@dataclass
class ProjectileSpec:
    """投掷物属性：不同类型有不同的重量、初速度、阻力与引信配置"""
    name: str
    mass: float               # kg
    initial_speed: float      # m/s
    drag_coefficient: float   # 空气阻力系数
    radius: float             # m，用于碰撞体积与截面积
    fuse_time: float          # 引信时间（秒）
    fuse_mode: str = "timer"  # "timer"=落地后计时 | "impact"=碰撞即爆


@dataclass
class Surface:
    """表面属性：弹性系数与摩擦系数"""
    name: str
    restitution: float  # 弹性系数 0~1
    friction: float     # 摩擦系数 0~1


@dataclass
class Projectile:
    """场景中的投掷物实例"""
    id: int
    spec: ProjectileSpec
    position: Vector3
    velocity: Vector3
    state: str = "flying"  # flying -> landed -> exploded -> destroyed
    has_landed: bool = False
    fuse_remaining: Optional[float] = None

    @property
    def active(self) -> bool:
        return self.state not in ("exploded", "destroyed")


DEFAULT_PROJECTILE_SPECS: Dict[str, ProjectileSpec] = {
    "grenade": ProjectileSpec("grenade", mass=0.4, initial_speed=25.0,
                              drag_coefficient=0.47, radius=0.06,
                              fuse_time=3.0, fuse_mode="timer"),
    "smoke": ProjectileSpec("smoke", mass=0.5, initial_speed=22.0,
                            drag_coefficient=0.47, radius=0.06,
                            fuse_time=2.0, fuse_mode="timer"),
    "rock": ProjectileSpec("rock", mass=1.0, initial_speed=15.0,
                           drag_coefficient=0.60, radius=0.08,
                           fuse_time=0.0, fuse_mode="impact"),
    "molotov": ProjectileSpec("molotov", mass=0.8, initial_speed=18.0,
                              drag_coefficient=0.50, radius=0.10,
                              fuse_time=0.0, fuse_mode="impact"),
}

DEFAULT_SURFACES: Dict[str, Surface] = {
    "concrete": Surface("concrete", restitution=0.6, friction=0.3),
    "grass": Surface("grass", restitution=0.25, friction=0.7),
    "wood": Surface("wood", restitution=0.45, friction=0.5),
    "default": Surface("default", restitution=0.5, friction=0.5),
}

DEFAULT_BOUNDS = {
    "x_min": -100.0, "x_max": 100.0,
    "y_min": 0.0, "y_max": 50.0,
    "z_min": -100.0, "z_max": 100.0,
}


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: Vector3, s: float) -> Vector3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Vector3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vector3) -> Vector3:
    length = _length(a)
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return _scale(a, 1.0 / length)


class ProjectileSystem:
    """投掷物系统核心类"""

    GRAVITY = GRAVITY
    AIR_DENSITY = AIR_DENSITY
    REST_SPEED_THRESHOLD = REST_SPEED_THRESHOLD

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.bounds = dict(DEFAULT_BOUNDS, **self.config.get("bounds", {}))
        self.projectile_specs = dict(DEFAULT_PROJECTILE_SPECS)
        self.projectile_specs.update(self.config.get("projectiles", {}))
        self.surfaces = dict(DEFAULT_SURFACES)
        self.surfaces.update(self.config.get("surfaces", {}))
        self.default_surface = self.config.get("surface", "concrete")
        self._projectiles: Dict[int, Projectile] = {}
        self._next_id = 0
        self._state = {}
        self._history = []

    # ------------------------------------------------------------------
    # 抛物线计算：考虑空气阻力与投掷物属性
    # ------------------------------------------------------------------
    def _drag_acceleration(self, spec: ProjectileSpec, velocity: Vector3) -> Vector3:
        """二次空气阻力: F = -0.5 * rho * Cd * A * |v| * v"""
        area = math.pi * spec.radius ** 2
        k = 0.5 * AIR_DENSITY * spec.drag_coefficient * area / spec.mass
        speed = _length(velocity)
        return _scale(velocity, -k * speed)

    def calculate_trajectory(self, projectile_type: str, position: Vector3,
                             direction: Vector3, dt: float = 0.01,
                             max_time: float = 30.0,
                             air_resistance: bool = True,
                             bounds: Optional[Dict] = None) -> List[Vector3]:
        """计算抛物线轨迹点列表。

        初速度取自投掷物配置（不再写死），可选择是否考虑空气阻力。
        轨迹在落地（触及 y_min）或超时后结束。
        """
        spec = self.projectile_specs[projectile_type]
        bounds = bounds or self.bounds
        pos = (float(position[0]), float(position[1]), float(position[2]))
        vel = _scale(_normalize(direction), spec.initial_speed)
        points = [pos]
        time_elapsed = 0.0
        while time_elapsed < max_time:
            acc = (0.0, -GRAVITY, 0.0)
            if air_resistance:
                acc = _add(acc, self._drag_acceleration(spec, vel))
            vel = _add(vel, _scale(acc, dt))
            pos = _add(pos, _scale(vel, dt))
            time_elapsed += dt
            if pos[1] <= bounds["y_min"] and vel[1] < 0.0:
                pos = (pos[0], bounds["y_min"], pos[2])
                points.append(pos)
                break
            points.append(pos)
        return points

    # ------------------------------------------------------------------
    # 碰撞检测与反射：支持地面/墙壁/天花板全方向
    # ------------------------------------------------------------------
    def collide_and_bounce(self, position: Vector3, velocity: Vector3,
                           bounds: Optional[Dict] = None,
                           radius: float = 0.0,
                           surface: Optional[str] = None
                           ) -> Tuple[Vector3, Vector3, Optional[Vector3]]:
        """检测与场景边界的碰撞并反弹。

        返回 (新位置, 新速度, 碰撞法线)；无碰撞时法线为 None。
        反射向量通过 bounce_physics 按表面属性计算。
        """
        bounds = bounds or self.bounds
        surface = surface or self.default_surface
        pos = [float(position[0]), float(position[1]), float(position[2])]
        normal = [0.0, 0.0, 0.0]
        hit = False
        axes = (("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max"))
        for axis, (lo_key, hi_key) in enumerate(axes):
            if pos[axis] - radius < bounds[lo_key]:
                pos[axis] = bounds[lo_key] + radius
                normal[axis] = 1.0
                hit = True
            elif pos[axis] + radius > bounds[hi_key]:
                pos[axis] = bounds[hi_key] - radius
                normal[axis] = -1.0
                hit = True
        if not hit:
            return (tuple(pos), velocity, None)
        new_velocity = self.bounce_physics(velocity, tuple(normal), surface)
        return (tuple(pos), new_velocity, tuple(normal))

    # ------------------------------------------------------------------
    # 弹跳物理：弹性按表面配置，含摩擦力
    # ------------------------------------------------------------------
    def bounce_physics(self, velocity: Vector3, normal: Vector3,
                       surface: Optional[str] = None) -> Vector3:
        """按表面属性计算碰撞后的速度。

        法向分量乘以弹性系数反向，切向分量乘以 (1 - 摩擦系数) 衰减；
        速度低于阈值时视为静止，避免无限滚动。
        """
        surface = surface or self.default_surface
        props = self.surfaces.get(surface, self.surfaces["default"])
        v_normal = _scale(normal, _dot(velocity, normal))
        v_tangent = _sub(velocity, v_normal)
        new_velocity = _add(
            _scale(v_tangent, max(0.0, 1.0 - props.friction)),
            _scale(v_normal, -props.restitution),
        )
        if _length(new_velocity) < REST_SPEED_THRESHOLD:
            return (0.0, 0.0, 0.0)
        return new_velocity

    # ------------------------------------------------------------------
    # 引信计时器：支持定时（落地后计时）与碰撞触发
    # ------------------------------------------------------------------
    def fuse_timer(self, projectile: Projectile, dt: float,
                   collided: bool = False) -> bool:
        """推进引信，返回是否应当爆炸。

        - impact 模式：发生碰撞立即爆炸；
        - timer 模式：落地后才开始计时，飞行中不会空爆。
        """
        spec = projectile.spec
        if spec.fuse_mode == "impact":
            return collided
        if not projectile.has_landed:
            return False
        if projectile.fuse_remaining is None:
            projectile.fuse_remaining = spec.fuse_time
        projectile.fuse_remaining -= dt
        return projectile.fuse_remaining <= 0.0

    # ------------------------------------------------------------------
    # 生命周期：飞行 -> 落地 -> 爆炸 -> 销毁
    # ------------------------------------------------------------------
    def projectile_lifecycle(self, projectile: Projectile, dt: float,
                             collided: bool = False,
                             landed: bool = False) -> str:
        """推进单个投掷物的生命周期，返回当前状态。

        collided 表示任意方向的碰撞（供 impact 引信使用）；
        landed 仅表示与地面接触（法线朝上），定时引信只在落地后启动。
        """
        if not projectile.active:
            return "destroyed"
        if landed:
            projectile.has_landed = True
            if projectile.state == "flying":
                projectile.state = "landed"
        if self.fuse_timer(projectile, dt, collided=collided):
            projectile.state = "exploded"
            self._history.append(("exploded", projectile.id))
            projectile.state = "destroyed"
            return "destroyed"
        return projectile.state

    # ------------------------------------------------------------------
    # 场景管理
    # ------------------------------------------------------------------
    def spawn(self, projectile_type: str, position: Vector3,
              direction: Vector3) -> Projectile:
        """按投掷物配置的初速度生成实例。"""
        spec = self.projectile_specs[projectile_type]
        velocity = _scale(_normalize(direction), spec.initial_speed)
        projectile = Projectile(id=self._next_id, spec=spec,
                                position=(float(position[0]), float(position[1]),
                                          float(position[2])),
                                velocity=velocity)
        self._projectiles[projectile.id] = projectile
        self._next_id += 1
        return projectile

    def get_projectile(self, projectile_id: int) -> Optional[Projectile]:
        return self._projectiles.get(projectile_id)

    @property
    def active_projectiles(self) -> List[Projectile]:
        return [p for p in self._projectiles.values() if p.active]

    def update(self, dt: float):
        """每帧更新：积分运动、碰撞反弹、引信与生命周期、清理销毁物。"""
        for projectile_id in list(self._projectiles):
            projectile = self._projectiles[projectile_id]
            if not projectile.active:
                del self._projectiles[projectile_id]
                continue
            acc = _add((0.0, -GRAVITY, 0.0),
                       self._drag_acceleration(projectile.spec, projectile.velocity))
            projectile.velocity = _add(projectile.velocity, _scale(acc, dt))
            projectile.position = _add(projectile.position,
                                       _scale(projectile.velocity, dt))
            pos, vel, normal = self.collide_and_bounce(
                projectile.position, projectile.velocity,
                radius=projectile.spec.radius)
            projectile.position = pos
            projectile.velocity = vel
            landed = normal is not None and normal[1] > 0.5
            state = self.projectile_lifecycle(projectile, dt,
                                              collided=normal is not None,
                                              landed=landed)
            if state == "destroyed":
                del self._projectiles[projectile_id]

    def reset(self):
        """重置状态"""
        self._projectiles = {}
        self._next_id = 0
        self._state = {}
        self._history = []
