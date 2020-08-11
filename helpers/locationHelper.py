import json
import urllib.request

from common.log import logUtils as log
from objects import glob


def getCountry(ip):
    """
    Get country from IP address using geoip api

    :param ip: IP address
    :return: country code. XX if invalid.
    """
    try:
        # Try to get country from Pikolo Aul's Go-Sanic ip API
        result = json.loads(urllib.request.urlopen("{}/{}".format(glob.conf.config["localize"]["ipapiurl"], ip), timeout=3).read().decode())["country"]
        return result.upper()
    except:
        log.error(f"Error in get country, ip: {ip}")
        return "XX"

def getLocation(ip):
    """
    Get latitude and longitude from IP address using geoip api

    :param ip: IP address
    :return: (latitude, longitude)
    """
    try:
        # Try to get position from Pikolo Aul's Go-Sanic ip API
        result = json.loads(urllib.request.urlopen("{}/{}".format(glob.conf.config["localize"]["ipapiurl"], ip), timeout=3).read().decode())["loc"].split(",")
        return float(result[0]), float(result[1])
    except:
        log.error(f"Error in get position, ip: {ip}")
        return 0, 0
