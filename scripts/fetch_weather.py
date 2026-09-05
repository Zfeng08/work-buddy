"""通过 Open-Meteo（免 key）抓取沈阳/昆明天气与空气质量，写入 data/weather.json。"""
import json
import sys
import time

from common import http_get, load_config, load_old, save_data


def fetch_city(city):
    base = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={city['lat']}&longitude={city['lon']}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=Asia%2FShanghai&forecast_days=5"
    )
    air = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={city['lat']}&longitude={city['lon']}"
        f"&current=pm2_5,pm10&timezone=Asia%2FShanghai"
    )
    w = http_get(base).json()
    try:
        a = http_get(air).json()
        pm25 = a["current"]["pm2_5"]
        pm10 = a["current"]["pm10"]
    except Exception:
        pm25 = pm10 = None

    cur = w["current"]
    return {
        "name": city["name"],
        "note": city.get("note", ""),
        "current": {
            "temperature": cur["temperature_2m"],
            "apparent": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"],
            "wind_speed": cur["wind_speed_10m"],
            "weather_code": cur["weather_code"],
            "pm25": pm25,
            "pm10": pm10,
            "time": cur.get("time", ""),
        },
        "daily": [
            {
                "date": w["daily"]["time"][i],
                "weather_code": w["daily"]["weather_code"][i],
                "temp_max": w["daily"]["temperature_2m_max"][i],
                "temp_min": w["daily"]["temperature_2m_min"][i],
                "precip_prob": w["daily"]["precipitation_probability_max"][i],
            }
            for i in range(len(w["daily"]["time"]))
        ],
    }


def main():
    cfg = load_config()["weather"]
    cities = []
    for city in cfg["cities"]:
        try:
            cities.append(fetch_city(city))
            print(f"[ok] {city['name']} 天气已获取")
        except Exception as e:
            print(f"[err] {city['name']}: {e}")

    if not cities:
        old = load_old("weather")
        if old:
            print("[warn] 全部失败，保留旧数据")
        return 0

    save_data("weather", {"cities": cities})
    return 0


if __name__ == "__main__":
    sys.exit(main())
