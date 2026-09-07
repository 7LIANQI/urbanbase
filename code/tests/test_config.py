"""测试 config.py 配置常量。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


class TestConfig:
    """验证配置模块常量。"""

    def test_openweather_url(self):
        """测试 OpenWeatherMap API URL。"""
        assert "openweathermap" in config.OPENWEATHER_AIR_POLLUTION_URL
        assert config.OPENWEATHER_AIR_POLLUTION_URL.startswith("https://")

    def test_baidu_urls(self):
        """测试百度地图相关 URL。"""
        assert "baidu" in config.BAIDU_PANORAMA_URL
        assert config.BAIDU_REFERER.startswith("https://")

    def test_lst_constants(self):
        """测试 Landsat 地表温度常量。"""
        assert isinstance(config.LST_SCALE, float)
        assert isinstance(config.LST_OFFSET, float)
        assert config.LST_KELVIN == 273.15

    def test_aqi_colors(self):
        """测试 AQI 颜色映射。"""
        assert len(config.AQI_COLORS) == 5
        assert config.AQI_COLORS[1] == "green"
        assert config.AQI_COLORS[5] == "purple"

    def test_pollutant_names(self):
        """测试污染物中文名称。"""
        assert len(config.POLLUTANT_NAMES) >= 8
        assert "pm2_5" in config.POLLUTANT_NAMES
        assert "pm10" in config.POLLUTANT_NAMES
        assert "CO" in config.POLLUTANT_NAMES["co"]
