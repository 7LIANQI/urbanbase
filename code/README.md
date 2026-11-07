# UrbanSense 代码目录

## 启动

```powershell
cd D:\大创urbanbase\code
python app.py
```

## 目录说明

```text
code/
├─ app.py                 程序入口
├─ core/                  核心配置、坐标、栅格目录、报告、通用工具
│  ├─ config.py            全局配置
│  ├─ utils.py             日志、密钥、网络重试
│  ├─ storage.py           默认存储目录
│  └─ summary_export.py    汇总宽表导出
├─ database/              SQLite 与 PostgreSQL
├─ collectors/            环境数据采集器与采集管线
├─ modules/               工具箱插件入口
├─ plugins/               GEE、本地栅格、OSM、天气等数据引擎
├─ ui/                    主窗口、地图、图层和工具页面
├─ scripts/               批量建库与数据整理脚本
└─ tests/                 自动化测试
```

运行产生的 `logs/`、输出目录和本地库数据不提交 Git。
