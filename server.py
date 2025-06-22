import asyncio
import aiohttp
import time
import json
import websockets

last_state_sums = {}
last_state_counts = {}
last_data = {}
connected_clients = set()

async def broadcast_data(data):
    if connected_clients:
        json_data = json.dumps(data)
        send_tasks = [client.send(json_data) for client in connected_clients]
        await asyncio.gather(*send_tasks)

async def process_text(rawa):
    global last_data, last_state_counts, last_state_sums
    data = {}
    for line in rawa.split("\n"):
        good = False
        for i in ["gateway_shard_latency{", "gateway_cache_guilds{", "gateway_shard_status_sum{", "gateway_shard_status_count{"]:
            if i in line:
                good = True
                break
        if not good:
            continue
        etype = line.split("{")[0]
        shard = int(line.split('{shard="')[1].split('"')[0])
        evalue = line.split(" ")[1]
        if evalue != "NaN":
            evalue = float(evalue)
        else:
            evalue = 0

        curr = data.get(shard, {})
        curr[etype] = evalue
        data[shard] = curr

    clean_data = {}
    for shard, values in data.items():
        last = last_data.get(shard, {})
        shard_data = {}
        shard_data["ping"] = round(values["gateway_shard_latency"] * 1000, 2) or last.get("ping", 0)
        shard_data["guilds"] = int(values["gateway_cache_guilds"]) or last.get("guilds", 0)
        if shard in last_state_counts and shard in last_state_sums:
            last_count = last_state_counts[shard]
            last_sum = last_state_sums[shard]
            if values["gateway_shard_status_count"] - 1 == last_count:
                shard_data["status"] = int(values["gateway_shard_status_sum"] - last_sum)
            else:
                shard_data["status"] = last.get("status", -1)
        else:
            shard_data["state"] = -1
        last_state_counts[shard] = values["gateway_shard_status_count"]
        last_state_sums[shard] = values["gateway_shard_status_sum"]
        shard_data["change"] = shard_data != last
        clean_data[shard] = shard_data
    result = {key: clean_data[key] for key in sorted(clean_data)}
    await broadcast_data(result)
    for key in result:
        result[key].pop('change', None)
    last_data = result

async def background_task():
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            async with session.get("http://localhost:7878/metrics") as response:
                await process_text(await response.text())
            elapsed_time = time.time() - start_time
            await asyncio.sleep(max(0, 0.9 - elapsed_time))

async def echo(websocket):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            await websocket.send(json.dumps(last_data))
    finally:
        connected_clients.remove(websocket)

async def main():
    server = await websockets.serve(echo, "0.0.0.0", 8765)
    await asyncio.gather(server.wait_closed(), background_task())

asyncio.run(main())
