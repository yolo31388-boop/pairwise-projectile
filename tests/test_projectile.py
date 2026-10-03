"""
投掷物系统 - 验收测试

运行方式：python -m pytest tests/test_projectile.py -q
共 13 个测试用例，覆盖：
- 抛物线：空气阻力、投掷物属性、初速度配置
- 碰撞：地面 / 墙壁 / 天花板全方向反射
- 弹跳：按表面配置的弹性与摩擦
- 生命周期：爆炸销毁、引信落地计时
- 引信：定时触发与碰撞触发
"""
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from projectile.system import ProjectileSystem


BOUNDS = {
    "x_min": -50.0, "x_max": 50.0,
    "y_min": 0.0, "y_max": 20.0,
    "z_min": -50.0, "z_max": 50.0,
}


def horizontal_range(points):
    return math.hypot(points[-1][0] - points[0][0],
                      points[-1][2] - points[0][2])


class TestProjectileSystem:
    """投掷物系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = ProjectileSystem(config={"bounds": dict(BOUNDS)})

    # ---- 抛物线 ----------------------------------------------------
    def test_case_01(self):
        """抛物线基本形状：先上升再下落，终点回到地面"""
        traj = self.system.calculate_trajectory(
            "grenade", (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
        assert len(traj) > 2
        ys = [p[1] for p in traj]
        assert max(ys) > 1.0
        assert ys[-1] <= 0.01
        assert ys.index(max(ys)) < len(ys) - 1

    def test_case_02(self):
        """空气阻力会缩短射程"""
        with_drag = self.system.calculate_trajectory(
            "grenade", (0.0, 1.0, 0.0), (1.0, 0.5, 0.0), air_resistance=True)
        no_drag = self.system.calculate_trajectory(
            "grenade", (0.0, 1.0, 0.0), (1.0, 0.5, 0.0), air_resistance=False)
        assert horizontal_range(with_drag) < horizontal_range(no_drag)

    def test_case_03(self):
        """不同投掷物有不同重量/属性，射程因此不同"""
        grenade = self.system.calculate_trajectory(
            "grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), air_resistance=False)
        rock = self.system.calculate_trajectory(
            "rock", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), air_resistance=False)
        g = self.system.projectile_specs["grenade"]
        r = self.system.projectile_specs["rock"]
        assert g.mass != r.mass
        assert g.drag_coefficient != r.drag_coefficient
        assert horizontal_range(grenade) > horizontal_range(rock)

    def test_case_04(self):
        """初速度来自投掷物配置而不是写死的常量"""
        grenade = self.system.spawn("grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        rock = self.system.spawn("rock", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        speed = lambda v: math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        assert math.isclose(speed(grenade.velocity),
                            self.system.projectile_specs["grenade"].initial_speed)
        assert math.isclose(speed(rock.velocity),
                            self.system.projectile_specs["rock"].initial_speed)
        assert speed(grenade.velocity) != speed(rock.velocity)

    # ---- 碰撞 ------------------------------------------------------
    def test_case_05(self):
        """与地面碰撞：垂直速度正确反射，位置不穿透"""
        pos, vel, normal = self.system.collide_and_bounce(
            (5.0, -0.1, 5.0), (0.0, -10.0, 0.0))
        assert normal == (0.0, 1.0, 0.0)
        assert vel[1] > 0.0
        assert pos[1] >= BOUNDS["y_min"]

    def test_case_06(self):
        """与墙壁碰撞：水平速度正确反射，位置被夹回边界内"""
        pos, vel, normal = self.system.collide_and_bounce(
            (60.0, 5.0, 0.0), (10.0, 0.0, 0.0))
        assert normal == (-1.0, 0.0, 0.0)
        assert vel[0] < 0.0
        assert pos[0] <= BOUNDS["x_max"]

    def test_case_07(self):
        """与天花板碰撞：向上速度反射为向下"""
        pos, vel, normal = self.system.collide_and_bounce(
            (0.0, 25.0, 0.0), (0.0, 10.0, 0.0))
        assert normal == (0.0, -1.0, 0.0)
        assert vel[1] < 0.0
        assert pos[1] <= BOUNDS["y_max"]

    # ---- 弹跳 ------------------------------------------------------
    def test_case_08(self):
        """弹性系数按表面配置：水泥地比草地弹得高"""
        on_concrete = self.system.bounce_physics(
            (0.0, -10.0, 0.0), (0.0, 1.0, 0.0), "concrete")
        on_grass = self.system.bounce_physics(
            (0.0, -10.0, 0.0), (0.0, 1.0, 0.0), "grass")
        assert on_concrete[1] > on_grass[1] > 0.0

    def test_case_09(self):
        """摩擦力衰减切向速度，反复弹跳后水平运动完全停止"""
        vel = (5.0, -0.1, 0.0)
        first = self.system.bounce_physics(vel, (0.0, 1.0, 0.0), "grass")
        assert first[0] < vel[0]
        for _ in range(200):
            vel = self.system.bounce_physics(vel, (0.0, 1.0, 0.0), "grass")
        assert vel == (0.0, 0.0, 0.0)

    # ---- 生命周期与引信 --------------------------------------------
    def test_case_10(self):
        """爆炸后投掷物被销毁并移出场景，不再参与碰撞"""
        projectile = self.system.spawn(
            "molotov", (0.0, 10.0, 0.0), (0.0, -1.0, 0.0))
        for _ in range(3000):
            self.system.update(0.01)
            if not projectile.active:
                break
        assert projectile.state == "destroyed"
        assert self.system.get_projectile(projectile.id) is None
        # 继续更新不会让已销毁的投掷物复活或报错
        self.system.update(0.01)
        assert self.system.get_projectile(projectile.id) is None

    def test_case_11(self):
        """定时引信从落地开始计时：高抛飞行超过引信时间也不在空中爆炸"""
        tall_bounds = dict(BOUNDS, y_max=50.0)
        self.system = ProjectileSystem(config={"bounds": tall_bounds})
        projectile = self.system.spawn(
            "grenade", (0.0, 1.0, 0.0), (0.0, 1.0, 0.0))
        fuse_time = self.system.projectile_specs["grenade"].fuse_time
        dt = 0.01
        elapsed = 0.0
        land_time = None
        explode_time = None
        while elapsed < 30.0:
            self.system.update(dt)
            elapsed += dt
            if land_time is None and projectile.has_landed:
                land_time = elapsed
            if projectile.state == "destroyed":
                explode_time = elapsed
                break
        assert land_time is not None
        assert land_time > fuse_time  # 飞行时间比引信长，旧逻辑会空中爆炸
        assert explode_time is not None
        assert math.isclose(explode_time - land_time, fuse_time, abs_tol=0.15)

    def test_case_12(self):
        """碰撞触发引信：砸到东西立即爆炸，不用等引信烧完"""
        projectile = self.system.spawn(
            "molotov", (0.0, 10.0, 0.0), (0.0, -1.0, 0.0))
        assert self.system.projectile_specs["molotov"].fuse_mode == "impact"
        frames = 0
        while projectile.active and frames < 3000:
            self.system.update(0.01)
            frames += 1
        assert projectile.state == "destroyed"
        assert projectile.has_landed
        assert frames < 2000

    def test_case_13(self):
        """定时引信飞行中不计时，落地之后才开始倒计时"""
        projectile = self.system.spawn(
            "grenade", (0.0, 30.0, 0.0), (0.0, 0.0, 0.0))
        fuse_time = self.system.projectile_specs["grenade"].fuse_time
        # 飞行时间已经超过引信时间，仍不应爆炸
        for _ in range(int((fuse_time + 2.0) / 0.01)):
            assert self.system.fuse_timer(projectile, 0.01, collided=False) is False
        assert projectile.fuse_remaining is None
        # 落地后引信开始倒计时并在 fuse_time 后爆炸
        projectile.has_landed = True
        exploded = False
        for _ in range(int((fuse_time + 1.0) / 0.01)):
            if self.system.fuse_timer(projectile, 0.01):
                exploded = True
                break
        assert exploded


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
