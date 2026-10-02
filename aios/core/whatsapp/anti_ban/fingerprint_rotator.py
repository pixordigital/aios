import random
DEVICES = ["SM-G991B","SM-A525F","Pixel 7","iPhone14,2","iPhone15,1"]
BROWSERS = ["Chrome/120.0","Chrome/119.0","Firefox/121.0"]
OS = ["Android 13","Android 14","iOS 17.1","Windows 10"]
def fingerprint_for(instance: str) -> dict:
    random.seed(abs(hash(instance)) % 9999)
    return {"deviceName": random.choice(DEVICES), "browser": random.choice(BROWSERS), "os": random.choice(OS), "userAgent": f"Mozilla/5.0 ({random.choice(OS)}) {random.choice(BROWSERS)}"}
