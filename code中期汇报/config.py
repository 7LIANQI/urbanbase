"""全局配置与常量。"""

# ---------- API 端点 ----------
OPENWEATHER_AIR_POLLUTION_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
BAIDU_PANORAMA_URL = "https://api.map.baidu.com/panorama/v2"

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
