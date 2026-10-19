# -*- coding: utf-8 -*-
"""geo.py —— 坐标变换（WGS-84 <-> GCJ-02）。

GCJ-02 是国测局对 WGS-84 的加偏结果，国内地图（高德 / 腾讯）使用 GCJ-02。
下面是实现公开的偏移算法（非保密），用于把真实经纬度按国内地图口径偏移 / 还原。
内部一律以 WGS-84 计算，导出时按需转 GCJ-02。
"""
import math

_A = 6378245.0
_EE = 0.00669342162296594323


def out_of_china(lng, lat):
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _dl_lat(lng, lat):
    r = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    r += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    r += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return r


def _dl_lng(lng, lat):
    r = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    r += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    r += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return r


def wgs84_to_gcj02(lng, lat):
    if out_of_china(lng, lat):
        return lng, lat
    dlat = _dl_lat(lng - 105.0, lat - 35.0)
    dlng = _dl_lng(lng - 105.0, lat - 35.0)
    rl = math.radians(lat)
    m = math.sin(rl)
    m = 1.0 - _EE * m * m
    sm = math.sqrt(m)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (m * sm) * math.pi)
    dlng = (dlng * 180.0) / (_A / sm * math.cos(rl) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat):
        return lng, lat
    g_lng, g_lat = wgs84_to_gcj02(lng, lat)
    return lng * 2.0 - g_lng, lat * 2.0 - g_lat


def haversine_m(lng1, lat1, lng2, lat2):
    """两点间距离（米），WGS-84 大圆距离。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def m_to_deg_lat(m):
    return m / 111320.0


def m_to_deg_lng(m, lat):
    return m / (111320.0 * math.cos(math.radians(lat)) or 1e-9)
