import os
import aiohttp
import asyncio
import json
import logging
import websockets
import time
import random
from datetime import datetime, timedelta
from itertools import cycle
from user_agent import generate_user_agent
from dotenv import load_dotenv
import sys

class Sniper:
    def __init__(self):
        self.start_time = None  # Track start time, initialized to None
        self.update_title("AX50 Vanity Sniper - Made By srry")  # Initial title
        load_dotenv()  # Load environment variables from .env file

        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%Y-%m-%d @ %H:%M:%S')
        self.logger = logging.getLogger("SNIPER")

        self.vanity_urls = self.load_vanity_urls()  # Load multiple vanitys
        self.guild_id = os.getenv("GUILD_ID")
        self.token = os.getenv("TOKEN")
        self.webhook_url = os.getenv("WEBHOOK_URL")

        self.headers = {"authorization": self.token, "user-agent": generate_user_agent()}

        self.use_proxy = self.prompt_proxy_usage()
        self.proxy_list = self.load_proxies_from_file("proxy.json") if self.use_proxy else []
        self.proxy_pool = cycle(self.proxy_list) if self.proxy_list else None
        self.proxy = next(self.proxy_pool) if self.proxy_pool else None

        self.gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"
        self.heartbeat_interval = None
        self.sequence = None
        self.vanity_claimed = {vanity: False for vanity in self.vanity_urls}
        self.stop_sniping = False  # Flag to stop further sniping once a vanity is claimed

        self.successful_heartbeats = 0
        self.failed_heartbeats = 0
        self.heartbeat_task = None
        self.exit_flag = False

        self.current_vanity_url = None  # Track the current vanity

        asyncio.create_task(self.update_title_periodically())  # Update title periodically

    def load_vanity_urls(self):
        filename = input(f"[{self.color_text('+', 'green')}] Enter vanity list: ")
        try:
            with open(filename, "r") as file:
                vanities = [line.strip() for line in file if line.strip()]
            self.update_title(f"{len(vanities)} vanities loaded")  # Update title with the number of vanities loaded
            return vanities
        except FileNotFoundError:
            self.logger.error("ERROR: File not found")
            return []
        except Exception as e:
            self.logger.error(f"Error reading vanity file, make sure its txt: {e}")
            return []

    def prompt_proxy_usage(self):
        while True:
            choice = input(f"[{self.color_text('?', 'yellow')}] Use proxy? Press 1 for No and 2 for Yes: ")
            if choice == "1":
                return False
            elif choice == "2":
                return True
            else:
                self.logger.error("Invalid choice, please enter 1 or 2.")

    def load_proxies_from_file(self, file_path):
        try:
            with open(file_path, "r") as file:
                proxy_data = json.load(file)
            if "proxies" in proxy_data and isinstance(proxy_data["proxies"], list):
                return proxy_data["proxies"]
            else:
                self.logger.error("Proxies key missing")
                return []
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load proxies: {e}")
            return []

    async def change_vanity(self, vanity_url):
        if self.stop_sniping:
            return  # Exit if sniping has already been stopped

        url = f"https://discord.com/api/v10/guilds/{self.guild_id}/vanity-url"
        proxy = self.build_proxy() if self.use_proxy else None
        start_time = time.perf_counter()
        payload = {"code": vanity_url}

        backoff_attempt = 0
        while not self.stop_sniping:
            async with self.session.patch(url, json=payload, headers=self.headers, proxy=proxy) as response:
                elapsed_time = time.perf_counter() - start_time
                if response.status == 200:
                    self.vanity_claimed[vanity_url] = True
                    self.stop_sniping = True  # Stop further sniping attempts
                    await self.send_claimed_message(vanity_url, f"{elapsed_time:.4f} seconds")  # Send webhook message when claimed
                    self.logger.info(f"discord.gg/{vanity_url} has been sniped successfully!")
                    self.logger.info(f"Time taken to snipe vanity: {elapsed_time:.4f} seconds")
                    self.heartbeat_task.cancel()
                    await self.close_session()
                    os.system(f'title AX50 - Successfully Sniped discord.gg/{vanity_url}') 
                    self.exit_flag = True  # Set exit flag to true
                    input(f"[{self.color_text('+', 'green')}] Press Enter to exit...") 
                    return
                elif response.status == 429:
                    self.logger.warning(f"ERROR: Rate limited while trying to snipe discord.gg/{vanity_url}. Stopping sniping.")
                    self.stop_sniping = True  # Stop further sniping attempts
                    self.heartbeat_task.cancel()
                    await self.close_session()
                    os.system(f'title AX50 - Rate Limited')
                    self.exit_flag = True  # Set exit flag to true
                    input(f"[{self.color_text('+', 'green')}] Press Enter to exit...")  # Wait for user input before exiting
                    return
                else:
                    self.logger.warning(f"ERROR: sniping discord.gg/{vanity_url}! Status Code: {response.status}")
                    return

    async def send_claimed_message(self, vanity_url, time_taken):
        embed = {
            "embeds": [
                {
                    "title": "New Vanity Snipe!",
                    "fields": [
                        {
                            "name": "__vanity__",
                            "value": f".gg/{vanity_url}",
                            "inline": True
                        },
                        {
                            "name": "__time taken__",
                            "value": f"{time_taken}",
                            "inline": True
                        }
                    ],
                    "color": 65280,  # Green
                    "footer": {
                        "text": "ax50 by srry"
                    }
                }
            ]
        }
        try:
            async with self.session.post(self.webhook_url, json=embed) as response:
                if response.status != 204:
                    self.logger.warning(f"Failed to send webhook message: {response.status}")
        except Exception as e:
            self.logger.error(f"send_claimed_message: {e}")

    def build_proxy(self):
        if self.proxy and isinstance(self.proxy, dict):
            proxy_url = f"http://{self.proxy['username']}:{self.proxy['password']}@{self.proxy['host']}:{self.proxy['port']}"
            return proxy_url
        else:
            return None

    async def send_heartbeat(self, websocket):
        try:
            while True:
                if self.start_time is None:  # Set start time on first heartbeat
                    self.start_time = datetime.now()
                heartbeat_payload = {
                    "op": 1,
                    "d": self.sequence
                }
                await websocket.send(json.dumps(heartbeat_payload))
                self.successful_heartbeats += 1
                self.update_heartbeat_counter()
                await asyncio.sleep(self.heartbeat_interval / 1000)
        except asyncio.CancelledError:
            self.failed_heartbeats += 1
            self.update_heartbeat_counter()

    def update_heartbeat_counter(self):
        if not self.stop_sniping:  # Only update if sniping has not been stopped
            sys.stdout.write(f"\r[{self.color_text('+', 'green')}] Successful Heartbeats: {self.successful_heartbeats} [{self.color_text('-', 'red')}] Failed Heartbeats: {self.failed_heartbeats}")
            sys.stdout.flush()

    async def listen_to_gateway(self):
        while not self.exit_flag:  # Retry mechanism
            try:
                async with websockets.connect(self.gateway_url, max_size=2**24) as websocket:
                    # Identify payload
                    identify_payload = {
                        "op": 2,
                        "d": {
                            "token": self.token,
                            "intents": 513,  # GUILD_CREATE and GUILD_UPDATE
                            "properties": {
                                "$os": "linux",
                                "$browser": "my_library",
                                "$device": "my_library"
                            }
                        }
                    }
                    await websocket.send(json.dumps(identify_payload))

                    try:
                        async for message in websocket:
                            if self.stop_sniping:
                                break  # Exit if sniping has already been stopped

                            event = json.loads(message)
                            if event["op"] == 10:  # Hello event
                                self.heartbeat_interval = event["d"]["heartbeat_interval"]
                                self.heartbeat_task = asyncio.create_task(self.send_heartbeat(websocket))
                            elif event["op"] == 0:  # Dispatch event
                                self.sequence = event["s"]
                                if event["t"] == "GUILD_UPDATE":
                                    guild = event["d"]
                                    old_vanity = guild.get("vanity_url_code", None)

                                    if old_vanity != self.current_vanity_url:
                                        self.update_heartbeat_counter()
                                        print()
                                        if old_vanity is None:
                                            self.logger.info("Vanity URL removed, attempting to snipe")
                                            await self.change_vanity(self.current_vanity_url)
                                        else:
                                            self.logger.info(f"Vanity URL changed from {old_vanity} to {self.current_vanity_url}, attempting to snipe")
                                            await self.change_vanity(old_vanity)
                                        
                                        self.current_vanity_url = old_vanity
                    except websockets.ConnectionClosed:
                        pass  # Do nothing on connection closed, retry will handle reconnection
            except Exception:
                pass  # Do nothing on exception, retry will handle reconnection

    async def start(self):
        async with aiohttp.ClientSession() as session:
            self.session = session
            guild_url = f"https://discord.com/api/v10/guilds/{self.guild_id}"
            async with self.session.get(guild_url, headers=self.headers) as response:
                if response.status == 200:
                    guild_info = await response.json()
                    self.current_vanity_url = guild_info.get("vanity_url_code")
                else:
                    self.logger.error(f"Failed to fetch guild info: {response.status}")
            if not self.stop_sniping:  # Only listen to gateway if sniping has not been stopped
                await self.listen_to_gateway()

    async def close_session(self):
        if self.session:
            await self.session.close()

    def color_text(self, text, color):
        colors = {
            "red": "\033[91m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "purple": "\033[95m",
            "reset": "\033[0m"
        }
        return f"{colors[color]}{text}{colors['reset']}"

    def update_title(self, custom_message=None):
        if self.start_time:
            elapsed_time = datetime.now() - self.start_time
            elapsed_str = str(elapsed_time).split('.')[0]  # Format elapsed time as hh:mm:ss
            title_message = f"HardScoping For {elapsed_str}"
            if custom_message:
                title_message += f" - {custom_message}"
            os.system(f'title AX50 Vanity Sniper - {title_message}')
        else:
            title_message = custom_message if custom_message else "AX50 Vanity Sniper"
            os.system(f'title {title_message}')

    async def update_title_periodically(self):
        while not self.stop_sniping:
            self.update_title()
            await asyncio.sleep(1)  # Update every second

async def main():
    sniper = Sniper()
    await sniper.start()

if __name__ == "__main__":
    asyncio.run(main())
