# 投掷物系统

## 项目描述

投掷物系统的bug修复项目。核心模块 `projectile/system.py` 的已知bug已全部修复，测试全部通过。

## 已修复的问题

- 抛物线已考虑空气阻力，初速度/重量按投掷物类型配置
- 碰撞检测支持地面/墙壁/天花板全方向，反射向量正确
- 弹性系数按表面配置（水泥/草地等），含摩擦力，投掷物会停下
- 爆炸后正确销毁并移出场景，定时引信从落地时开始计时
- 引信支持定时触发与碰撞触发两种模式

## 项目结构

```
├── projectile/system.py       # 核心模块（带bug）
├── tests/test_projectile.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_projectile.py -q
```

修复目标：所有 13 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
