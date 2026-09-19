"""全局配置与常量。"""

# ---------- API 端点 ----------
OPENWEATHER_AIR_POLLUTION_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
BAIDU_PANORAMA_URL = "https://api.map.baidu.com/panorama/v2"
BAIDU_REFERER = "https://lbsyun.baidu.com/"   # 浏览器端 AK 白名单校验用

# ---------- 遥感常量 ----------
LST_SCALE = 0.00341802       # Landsat ST_B10 缩放系数
LST_OFFSET = 149.0           # Landsat ST_B10 偏移量
LST_KELVIN = 273.15          # 开尔文 → 摄氏度

# ---------- 空气质量 ----------
AQI_COLORS = {
    1: "green",
    2: "#DAA520",
    3: "orange",
    4: "red",
    5: "purple",
}

POLLUTANT_NAMES = {
    "co":   "CO (一氧化碳)",
    "no":   "NO (一氧化氮)",
    "no2":  "NO2 (二氧化氮)",
    "o3":   "O3 (臭氧)",
    "so2":  "SO2 (二氧化硫)",
    "pm2_5": "PM2.5",
    "pm10": "PM10",
    "nh3":  "NH3 (氨气)",
}

# ---------- PostgreSQL 本地库 ----------
PG_HOST = "localhost"
PG_PORT = 5432
PG_DBNAME = "urban_analysis"
PG_USER = "postgres"
PG_PASSWORD = "postgres"   # 本地开发默认密码（仅监听本机），多人共享时请修改

# ---------- PostgreSQL 便携版二进制路径（与 scripts/*.bat 保持一致） ----------
PG_BIN_DIR = r"D:\PostgreSQL17\pgsql\bin"
PG_DATA_DIR = r"D:\PostgreSQL17\data"
PG_LOG_PATH = r"D:\PostgreSQL17\pg.log"
