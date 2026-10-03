# 投掷物系统

## 项目描述

投掷物系统的bug修复项目。核心模块 `projectile/system.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 抛物线无空气阻力初速写死
- 碰撞只查地面不查墙和天花板
- 弹性系数写死无摩擦力
- 爆炸后不销毁计时器从扔出时算
- 引信不支持碰撞触发

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
