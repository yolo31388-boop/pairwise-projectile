"""
投掷物系统 - 验收测试

运行方式：python -m pytest tests/test_projectile.py -q
共 13 个测试用例
"""
import math

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from projectile.system import ProjectileSystem


def _step(system, seconds, dt=0.02):
    """按固定步长推进系统若干帧"""
    steps = int(round(seconds / dt))
    for _ in range(steps):
        system.update(dt)


class TestProjectileSystem:
    """投掷物系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = ProjectileSystem()

    def test_case_01(self):
        """空气阻力：带阻力的射程与最大高度必须小于真空理论值"""
        direction = (1.0 / math.sqrt(2), 1.0 / math.sqrt(2), 0.0)
        traj = self.system.calculate_trajectory("grenade", (0.0, 1.0, 0.0), direction)

        speed = 25.0
        vacuum_range = speed ** 2 / 9.81                    # sin(2*45°) = 1
        vacuum_height = 1.0 + (speed * math.sin(math.radians(45))) ** 2 / (2 * 9.81)

        final_x = traj[-1][0]
        max_y = max(p[1] for p in traj)
        assert 0.0 < final_x < vacuum_range
        assert max_y < vacuum_height

    def test_case_02(self):
        """投掷物属性：不同类型的质量/初速度不同，初速度不得写死"""
        grenade = self.system.spawn("grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        rock = self.system.spawn("rock", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))

        g_speed = math.sqrt(sum(c * c for c in grenade["velocity"]))
        r_speed = math.sqrt(sum(c * c for c in rock["velocity"]))
        assert g_speed == pytest.approx(25.0)
        assert r_speed == pytest.approx(15.0)

        # 初速度可被显式覆盖，不是写死值
        fast = self.system.spawn("grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), speed=40.0)
        f_speed = math.sqrt(sum(c * c for c in fast["velocity"]))
        assert f_speed == pytest.approx(40.0)

        # 不同类型弹道不同
        t_g = self.system.calculate_trajectory("grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        t_r = self.system.calculate_trajectory("rock", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        assert t_g[-1][0] != pytest.approx(t_r[-1][0])

    def test_case_03(self):
        """抛物线形状：从起点出发，先升后降，最终落回地面"""
        traj = self.system.calculate_trajectory(
            "grenade", (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
        assert traj[0] == pytest.approx((0.0, 1.0, 0.0))
        assert max(p[1] for p in traj) > 1.0
        assert traj[-1][1] <= 0.1 + 1e-6  # 半径 0.1，落回地面
        xs = [p[0] for p in traj]
        assert all(b >= a - 1e-9 for a, b in zip(xs, xs[1:]))  # 水平单调前进

    def test_case_04(self):
        """墙壁碰撞：不得穿墙，x 方向速度必须反向"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_mode": "none"}},
            "world": {"bounds": {"x": (-5.0, 5.0), "y": (0.0, 50.0), "z": (-5.0, 5.0)}},
        })
        proj = system.spawn("grenade", (4.5, 1.0, 0.0), (1.0, 0.0, 0.0), speed=10.0)
        for _ in range(50):
            system.update(0.02)
            assert proj["position"][0] <= 5.0 - proj["radius"] + 1e-6
        assert proj["velocity"][0] < 0.0

    def test_case_05(self):
        """天花板碰撞：不得穿出，垂直速度必须反向"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_mode": "none"}},
            "world": {"bounds": {"x": (-50.0, 50.0), "y": (0.0, 3.0), "z": (-50.0, 50.0)}},
        })
        proj = system.spawn("grenade", (0.0, 2.5, 0.0), (0.0, 1.0, 0.0), speed=10.0)
        for _ in range(50):
            system.update(0.02)
            assert proj["position"][1] <= 3.0 - proj["radius"] + 1e-6
        assert proj["velocity"][1] < 0.0

    def test_case_06(self):
        """地面碰撞：不得穿透地面，且必须发生反弹"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_mode": "none"}},
        })
        proj = system.spawn("grenade", (0.0, 2.0, 0.0), (0.0, -1.0, 0.0), speed=5.0)
        min_y = float("inf")
        bounced = False
        for _ in range(30):
            system.update(0.02)
            min_y = min(min_y, proj["position"][1])
            if proj["velocity"][1] > 0.0:
                bounced = True
        assert min_y >= proj["radius"] - 1e-6
        assert bounced

    def test_case_07(self):
        """反射向量：v' = v - 2(v·n)n，入射角等于反射角"""
        surface = {"restitution": 1.0, "friction": 0.0}
        # 地面法线
        v = self.system.bounce_physics((3.0, -4.0, 0.0), (0.0, 1.0, 0.0), surface)
        assert v == pytest.approx((3.0, 4.0, 0.0))
        # 墙面法线
        v2 = self.system.bounce_physics((3.0, 4.0, 0.0), (-1.0, 0.0, 0.0), surface)
        assert v2 == pytest.approx((-3.0, 4.0, 0.0))

    def test_case_08(self):
        """表面弹性：水泥地反弹高于草地，弹性系数不得写死"""
        v_concrete = self.system.bounce_physics(
            (0.0, -10.0, 0.0), (0.0, 1.0, 0.0), self.system.surfaces["concrete"])
        v_grass = self.system.bounce_physics(
            (0.0, -10.0, 0.0), (0.0, 1.0, 0.0), self.system.surfaces["grass"])
        assert v_concrete[1] > v_grass[1] > 0.0
        assert v_concrete[1] == pytest.approx(6.0)   # restitution 0.6
        assert v_grass[1] == pytest.approx(2.5)      # restitution 0.25

    def test_case_09(self):
        """摩擦力：切向速度被衰减，草地上的投掷物最终停下"""
        v = self.system.bounce_physics(
            (10.0, -10.0, 0.0), (0.0, 1.0, 0.0),
            {"restitution": 0.5, "friction": 0.5})
        assert 0.0 < v[0] < 10.0  # 水平分量被摩擦衰减

        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_mode": "none"}},
            "world": {"surfaces": {"ground": "grass"}},
        })
        proj = system.spawn("grenade", (0.0, 0.5, 0.0), (1.0, 0.2, 0.0), speed=8.0)
        _step(system, 10.0)
        speed = math.sqrt(sum(c * c for c in proj["velocity"]))
        assert proj["state"] == "landed"
        assert speed == pytest.approx(0.0)

    def test_case_10(self):
        """生命周期：爆炸后必须销毁并移出场景，不再参与碰撞"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_time": 0.05, "fuse_starts_on": "throw"}},
        })
        proj = system.spawn("grenade", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        _step(system, 0.2)
        assert proj["state"] == "destroyed"
        assert proj not in system.active_projectiles
        assert len(system.explosions) == 1
        # 销毁后继续更新：不再移动、不再产生新的爆炸
        pos = proj["position"]
        _step(system, 0.2)
        assert proj["position"] == pos
        assert len(system.explosions) == 1

    def test_case_11(self):
        """引信从落地起算：高抛手雷飞行时间超过引信也不得空爆"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_time": 1.0, "fuse_starts_on": "land"}},
            "world": {"bounds": {"y": (0.0, 100.0)}, "surfaces": {"ground": "grass"}},
        })
        proj = system.spawn("grenade", (0.0, 1.0, 0.0), (0.0, 1.0, 0.0), speed=15.0)
        _step(system, 2.0)  # 仍在空中飞行，引信未起算，不得空爆
        assert proj["state"] == "flying"
        assert len(system.explosions) == 0
        _step(system, 8.0)  # 落地静止后引信烧完
        assert proj["state"] == "destroyed"
        assert len(system.explosions) == 1

    def test_case_12(self):
        """碰撞触发引信：砸到目标立即爆炸，无需等引信烧完"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_mode": "impact", "fuse_time": 99.0}},
        })
        proj = system.spawn("grenade", (0.0, 0.5, 0.0), (0.0, -1.0, 0.0), speed=5.0)
        _step(system, 1.0)
        assert proj["state"] == "destroyed"
        assert len(system.explosions) == 1
        # 爆炸点应在地面附近（碰撞点）
        assert system.explosions[0]["position"][1] <= proj["radius"] + 0.05

    def test_case_13(self):
        """完整生命周期：flying -> 落地 -> 引信 -> exploded -> destroyed"""
        system = ProjectileSystem(config={
            "projectiles": {"grenade": {"fuse_time": 0.5, "fuse_starts_on": "land"}},
        })
        proj = system.spawn("grenade", (0.0, 2.0, 0.0), (1.0, 0.5, 0.0), speed=10.0)
        assert proj["state"] == "flying"

        states = []
        for _ in range(300):
            system.update(0.02)
            states.append(proj["state"])
            if proj["state"] == "destroyed":
                break

        assert states[0] == "flying"
        assert proj["touched_ground"]
        assert "exploded" in states
        assert states[-1] == "destroyed"
        assert proj not in system.active_projectiles
        assert len(system.explosions) == 1
        # 爆炸发生在落地之后，位置贴近地面
        assert system.explosions[0]["position"][1] <= proj["radius"] + 0.05


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
