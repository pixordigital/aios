"""k6 / chaos stub: baseline 100 inst, 10k msg/min"""
import asyncio
from aios.core.whatsapp.service import send_via_gateway
async def soak():
    for i in range(100):
        await send_via_gateway(f"test-{i%10}", f"551199{i:08d}", "soak")
if __name__=="__main__": asyncio.run(soak())
