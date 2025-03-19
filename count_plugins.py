#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
import logging
import subprocess

# 获取当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 配置日志目录
LOGS_DIR = os.environ.get('LOGS_DIR', os.path.join(SCRIPT_DIR, 'logs'))
os.makedirs(LOGS_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, 'plugin_counter.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('plugin_counter')

# 从环境变量获取配置
REPOS_DIR = os.environ.get('REPOS_DIR', os.path.join(SCRIPT_DIR, 'repos'))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(SCRIPT_DIR, 'data'))

# 确保目录存在
os.makedirs(REPOS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Paths
DIFY_PLUGINS_REPO = os.path.join(REPOS_DIR, "dify-plugins")
DIFY_OFFICIAL_PLUGINS_REPO = os.path.join(REPOS_DIR, "dify-official-plugins")
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', "https://open.feishu.cn/open-apis/bot/v2/hook/70eb61f9-7b92-46ce-b462-0e544c1612dd")
HISTORY_FILE = os.path.join(DATA_DIR, "plugin_history.json")

def ensure_repo_exists(repo_path, repo_url):
    """Ensure the repository exists, clone it if it doesn't"""
    # 如果目录不存在，创建并克隆
    if not os.path.exists(repo_path):
        logger.info(f"Repository path {repo_path} does not exist, cloning...")
        parent_dir = os.path.dirname(repo_path)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        os.chdir(parent_dir)
        clone_result = os.system(f"git clone {repo_url} {os.path.basename(repo_path)}")
        if clone_result != 0:
            logger.error(f"Failed to clone repository {repo_url}")
            return False
        return True
    
    # 如果目录存在，检查是否是有效的Git仓库
    os.chdir(repo_path)
    is_git_repo = os.system("git rev-parse --is-inside-work-tree > /dev/null 2>&1") == 0
    
    if not is_git_repo:
        logger.warning(f"{repo_path} exists but is not a valid Git repository. Will remove and re-clone.")
        # 备份目录名
        backup_dir = f"{repo_path}_bak_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        os.rename(repo_path, backup_dir)
        # 重新克隆
        parent_dir = os.path.dirname(repo_path)
        os.chdir(parent_dir)
        clone_result = os.system(f"git clone {repo_url} {os.path.basename(repo_path)}")
        if clone_result != 0:
            logger.error(f"Failed to clone repository {repo_url}")
            # 如果克隆失败，恢复备份
            os.rename(backup_dir, repo_path)
            return False
        return True
    
    # 如果是有效的Git仓库，更新它
    logger.info(f"Updating existing repository {repo_path}")
    pull_result = os.system("git pull")
    if pull_result != 0:
        logger.warning(f"Failed to pull latest changes for {repo_path}")
    
    return True

def get_commit_count_last_24h(repo_path):
    """Get the number of commits in the last 24 hours"""
    try:
        os.chdir(repo_path)
        cmd = ['git', 'log', '--since=24.hours', '--oneline']
        result = subprocess.run(cmd, capture_output=True, text=True)
        commits = result.stdout.strip().split('\n')
        # Filter out empty lines which happens if there are no commits
        commits = [c for c in commits if c]
        return len(commits)
    except Exception as e:
        logger.error(f"Error getting commit count: {str(e)}")
        return 0

def count_plugins_community(repo_path):
    """
    Count the number of plugins in the community repository according to the following rules:
    1. Each subdirectory in a plugin directory counts as a plugin
    2. A directory with .difypkg file also counts as a plugin
    3. Multiple .difypkg files in a directory without subdirectories count as a single plugin
    """
    if not os.path.exists(repo_path):
        logger.error(f"Repository path {repo_path} does not exist")
        return 0
    
    try:
        # Pull the latest changes
        os.chdir(repo_path)
        os.system("git pull")
        
        total_plugins = 0
        
        # Skip these directories as they're not plugin directories
        skip_dirs = ['.git', '.github', '.assets', 'logs']
        
        # Get all immediate subdirectories (plugin author directories)
        for author_dir in os.listdir(repo_path):
            author_path = os.path.join(repo_path, author_dir)
            
            # Skip non-directories and special directories
            if not os.path.isdir(author_path) or author_dir in skip_dirs or author_dir.startswith('.'):
                continue
            
            logger.info(f"Checking author directory: {author_dir}")
            
            # Check each plugin directory under the author
            for plugin_dir in os.listdir(author_path):
                plugin_path = os.path.join(author_path, plugin_dir)
                
                # Skip non-directories
                if not os.path.isdir(plugin_path):
                    continue
                
                # Count subdirectories and .difypkg files in this plugin directory
                has_subdirs = False
                difypkg_count = 0
                
                for item in os.listdir(plugin_path):
                    item_path = os.path.join(plugin_path, item)
                    if os.path.isdir(item_path):
                        has_subdirs = True
                        total_plugins += 1
                        logger.info(f"  Found plugin subdirectory: {os.path.join(plugin_dir, item)}")
                    elif item.endswith('.difypkg'):
                        difypkg_count += 1
                
                # If there are no subdirectories but there are .difypkg files, count as one plugin
                if not has_subdirs and difypkg_count > 0:
                    total_plugins += 1
                    logger.info(f"  Found plugin with {difypkg_count} .difypkg files: {plugin_dir}")
        
        logger.info(f"Total community plugins counted: {total_plugins}")
        return total_plugins
    
    except Exception as e:
        logger.error(f"Error counting community plugins: {str(e)}")
        return 0

def count_plugins_official(repo_path):
    """
    Count the number of plugins in the official repository:
    Each subdirectory in the main plugin categories (agent-strategies, extensions, models, tools, migrations)
    counts as a plugin.
    """
    if not os.path.exists(repo_path):
        logger.error(f"Repository path {repo_path} does not exist")
        return 0
    
    try:
        # Pull the latest changes
        os.chdir(repo_path)
        os.system("git pull")
        
        total_plugins = 0
        plugin_categories = ['agent-strategies', 'extensions', 'models', 'tools', 'migrations']
        
        for category in plugin_categories:
            category_path = os.path.join(repo_path, category)
            if not os.path.isdir(category_path):
                continue
                
            logger.info(f"Checking official category: {category}")
            
            # Count each subdirectory as a plugin
            for plugin_dir in os.listdir(category_path):
                plugin_path = os.path.join(category_path, plugin_dir)
                if os.path.isdir(plugin_path):
                    total_plugins += 1
                    logger.info(f"  Found official plugin: {os.path.join(category, plugin_dir)}")
        
        logger.info(f"Total official plugins counted: {total_plugins}")
        return total_plugins
    
    except Exception as e:
        logger.error(f"Error counting official plugins: {str(e)}")
        return 0

def load_history():
    """Load plugin count history from file"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading history: {str(e)}")
    return {"community": {}, "official": {}}

def save_history(history):
    """Save plugin count history to file"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        logger.error(f"Error saving history: {str(e)}")

def calculate_new_plugins(history, community_count, official_count):
    """Calculate the number of new plugins in the last 24 hours"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Check if we have any history data
    has_previous_data = False
    
    # Get the most recent date in history (if any)
    community_dates = sorted([d for d in history["community"].keys()], reverse=True)
    official_dates = sorted([d for d in history["official"].keys()], reverse=True)
    
    # Determine if we have usable history data (not just from today)
    if community_dates and official_dates:
        prev_dates = set(community_dates) | set(official_dates)
        prev_dates.discard(today)  # Exclude today from previous dates
        has_previous_data = len(prev_dates) > 0
    
    # If this is the first run or we only have today's data:
    if not has_previous_data:
        # Update history with today's counts but report 0 new plugins
        history["community"][today] = community_count
        history["official"][today] = official_count
        return 0, 0, 0
        
    # Get the most recent counts
    community_previous = 0
    official_previous = 0
    
    # Find the most recent data point before today
    prev_community_dates = [d for d in community_dates if d != today]
    prev_official_dates = [d for d in official_dates if d != today]
    
    if prev_community_dates:
        community_previous = history["community"][prev_community_dates[0]]
    
    if prev_official_dates:
        official_previous = history["official"][prev_official_dates[0]]
    
    # Calculate the difference
    community_new = max(0, community_count - community_previous)
    official_new = max(0, official_count - official_previous)
    total_new = community_new + official_new
    
    # Update history with today's counts
    history["community"][today] = community_count
    history["official"][today] = official_count
    
    return community_new, official_new, total_new

def send_to_feishu(community_count, official_count, community_new, official_new, total_new):
    """Send the plugin counts to Feishu webhook"""
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_count = community_count + official_count
        remaining_to_500 = max(0, 500 - total_count)
        
        message = {
            "msg_type": "text",
            "content": {
                "text": (
                    f"Dify Plugins Count Update ({current_time}):\n\n"
                    f"Total Plugins: {total_count}\n"
                    f"- Community Plugins: {community_count}\n"
                    f"- Official Plugins: {official_count}\n\n"
                    f"New Plugins (24h): {total_new}\n\n"
                    f"Plugins needed to reach 500: {remaining_to_500}\n\n"
                    f"Repositories:\n"
                    f"- https://github.com/langgenius/dify-plugins\n"
                    f"- https://github.com/langgenius/dify-official-plugins"
                )
            }
        }
        
        response = requests.post(FEISHU_WEBHOOK, json=message)
        
        if response.status_code == 200:
            logger.info("Successfully sent message to Feishu")
        else:
            logger.error(f"Failed to send message to Feishu. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
    
    except Exception as e:
        logger.error(f"Error sending message to Feishu: {str(e)}")

def main():
    logger.info("Starting plugin count process")
    
    # Ensure repositories exist
    community_repo_ok = ensure_repo_exists(DIFY_PLUGINS_REPO, "https://github.com/langgenius/dify-plugins.git")
    official_repo_ok = ensure_repo_exists(DIFY_OFFICIAL_PLUGINS_REPO, "https://github.com/langgenius/dify-official-plugins.git")
    
    # Count plugins
    community_count = count_plugins_community(DIFY_PLUGINS_REPO) if community_repo_ok else 0
    official_count = count_plugins_official(DIFY_OFFICIAL_PLUGINS_REPO) if official_repo_ok else 0
    
    # Load history and calculate new plugins
    history = load_history()
    community_new, official_new, total_new = calculate_new_plugins(history, community_count, official_count)
    save_history(history)
    
    if community_count > 0 and official_count > 0:
        send_to_feishu(community_count, official_count, community_new, official_new, total_new)
    else:
        logger.warning("Skipping Feishu notification because plugin count is zero")
    
    logger.info("Finished plugin count process")

if __name__ == "__main__":
    main() 