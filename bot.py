import logging
import subprocess
import os
import re
import random
import discord
from discord.ext import commands
import docker
import asyncio
from discord import app_commands
import requests

TOKEN = 'YOUR_BOT_TOKEN'
RAM_LIMIT = '6g'
SERVER_LIMIT = 2
database_file = 'database.txt'
suspended_file = 'suspended.txt'
deployment_channel_id = 1344671118711328879  # Default deployment channel

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)
client = docker.from_env()

whitelist_ids = {"1128161197766746213"}  # Replace with actual admin user IDs

def save_deployment_channel(channel_id):
    """Save the deployment channel ID to a file."""
    with open("deployment_channel.txt", "w") as f:
        f.write(str(channel_id))

def load_deployment_channel():
    """Load the deployment channel ID from a file."""
    if os.path.exists("deployment_channel.txt"):
        with open("deployment_channel.txt", "r") as f:
            return int(f.read().strip())
    return deployment_channel_id  # Default if file is missing

deployment_channel_id = load_deployment_channel()  # Load saved channel ID on startup

def add_to_database(userid, container_name):
    with open(database_file, 'a') as f:
        f.write(f"{userid}|{container_name}\n")

def remove_from_database(container_name):
    if not os.path.exists(database_file):
        return
    with open(database_file, 'r') as f:
        lines = f.readlines()
    with open(database_file, 'w') as f:
        for line in lines:
            if container_name not in line:
                f.write(line)

def get_user_servers(userid):
    if not os.path.exists(database_file):
        return []
    servers = []
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(userid):
                servers.append(line.strip())
    return servers

def get_container_id_from_database(userid, container_name):
    if not os.path.exists(database_file):
        return None
    with open(database_file, 'r') as f:
        for line in f:
            if line.startswith(userid) and container_name in line:
                return line.split('|')[1]
    return None

def get_creator_from_database(container_name):
    if not os.path.exists(database_file):
        return "Unknown"
    with open(database_file, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 2 and parts[1] == container_name:
                return parts[0]  # User ID
    return "Unknown"

def get_vps_id_from_database(container_name):
    if not os.path.exists(suspended_file):
        return "Unknown"
    with open(suspended_file, 'r') as f:
        for line in f:
            if container_name in line:
                return line.split('VPS ')[-1].strip()
    return "Unknown"

def get_memory_usage():
    """Fetch system memory usage."""
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
        mem_total = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1)) / 1024
        mem_available = int(re.search(r'MemAvailable:\s+(\d+)', meminfo).group(1)) / 1024
        memory_used = mem_total - mem_available
        memory_percentage = (memory_used / mem_total) * 100 if mem_total else 0
        return f"{memory_used:.2f} / {mem_total:.2f} MB ({memory_percentage:.2f}%)"
    except Exception as e:
        return f"Error fetching memory usage: {e}"

@bot.tree.command(name="node", description="Show the current status of the VPS node.")
async def node_status(interaction: discord.Interaction):
    try:
        containers = client.containers.list(all=True)
        if not containers:
            await interaction.response.send_message(embed=discord.Embed(
                description="No containers found on this node.", color=0xff0000))
            return

        container_info = []
        for container in containers:
            container_name = container.name
            container_status = container.status
            creator_id = get_creator_from_database(container_name)
            vps_id = get_vps_id_from_database(container_name)
            container_info.append(f"**{container_name}** - `{container_status}`\n**Created by:** <@{creator_id}>\n**VPS ID:** `{vps_id}`")

        pages = []
        page_size = 5
        for i in range(0, len(container_info), page_size):
            pages.append("\n".join(container_info[i:i + page_size]))

        embed = discord.Embed(title="VPS Node Status", color=0x00ff00)
        embed.add_field(name="Memory Usage", value=get_memory_usage(), inline=False)

        for idx, page in enumerate(pages):
            embed.add_field(name=f"Page {idx + 1}", value=page, inline=False)

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        await interaction.response.send_message(embed=discord.Embed(
            description=f"### Failed to fetch node status: {str(e)}", color=0xff0000))

@bot.tree.command(name="suspendvps", description="Suspends a user's VPS. Admin only.")
@app_commands.describe(container_name="The name of the VPS instance", user_id="The Discord user ID")
async def suspend_vps(interaction: discord.Interaction, container_name: str, user_id: str):
    if str(interaction.user.id) not in whitelist_ids:
        await interaction.response.send_message(embed=discord.Embed(
            description="You do not have permission to use this command.", color=0xff0000))
        return

    container_id = get_container_id_from_database(user_id, container_name)

    if not container_id:
        await interaction.response.send_message(embed=discord.Embed(
            description="No active instance found for the specified user.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "stop", container_id], check=True)

        with open(suspended_file, "a") as log:
            log.write(f"{container_name} - Suspended | Created by: {user_id} | VPS ID: {container_id}\n")

        await interaction.response.send_message(embed=discord.Embed(
            description=f"VPS '{container_name}' for user <@{user_id}> has been suspended.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(
            description=f"Error suspending VPS: {e}", color=0xff0000))

@bot.tree.command(name="unsuspendvps", description="Unsuspends a user's VPS. Admin only.")
@app_commands.describe(container_name="The name of the VPS instance")
async def unsuspend_vps(interaction: discord.Interaction, container_name: str):
    if str(interaction.user.id) not in whitelist_ids:
        await interaction.response.send_message(embed=discord.Embed(
            description="You do not have permission to use this command.", color=0xff0000))
        return

    try:
        subprocess.run(["docker", "start", container_name], check=True)

        with open(suspended_file, "r") as f:
            lines = f.readlines()
        with open(suspended_file, "w") as f:
            for line in lines:
                if container_name not in line:
                    f.write(line)

        await interaction.response.send_message(embed=discord.Embed(
            description=f"VPS '{container_name}' has been unsuspended.", color=0x00ff00))
    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(embed=discord.Embed(
            description=f"Error unsuspending VPS: {e}", color=0xff0000))

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    await bot.tree.sync()

bot.run(TOKEN)
