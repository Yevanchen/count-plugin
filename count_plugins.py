#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timedelta
import logging
import subprocess
import signal
import resource
import sys
import time

# 设置资源限制，防止脚本使用过多资源导致服务器崩溃
def set_resource_limits():
    # 设置内存限制 (1GB)
    MB = 1024 * 1024
    GB = 1024 * MB
    resource.setrlimit(resource.RLIMIT_AS, (1 * GB, 1 * GB))
    
    # 设置CPU时间限制 (5分钟)
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))

# 超时处理装饰器
def timeout_handler(signum, frame):
    raise TimeoutError("操作超时")

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

# 设置Git操作超时时间（秒）
GIT_OPERATION_TIMEOUT = 300  # 5分钟超时

# 设置网络请求超时（秒）
REQUEST_TIMEOUT = 30

def run_with_timeout(func, *args, timeout=300, **kwargs):
    """运行函数并设置超时"""
    # 设置SIGALRM处理函数
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    
    try:
        result = func(*args, **kwargs)
        signal.alarm(0)  # 取消定时器
        return result
    except TimeoutError as e:
        logger.error(f"操作超时: {func.__name__}")
        raise
    finally:
        signal.alarm(0)  # 确保取消定时器

def ensure_repo_exists(repo_path, repo_url):
    """Ensure the repository exists, clone it if it doesn't"""
    # 如果目录不存在，创建并克隆
    if not os.path.exists(repo_path):
        logger.info(f"Repository path {repo_path} does not exist, cloning...")
        parent_dir = os.path.dirname(repo_path)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        os.chdir(parent_dir)
        
        try:
            # 使用带超时的克隆命令
            cmd = f"git clone --depth 1 {repo_url} {os.path.basename(repo_path)}"
            logger.info(f"Running command: {cmd}")
            
            # 使用timeout命令限制Git操作时间
            clone_process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = clone_process.communicate(timeout=GIT_OPERATION_TIMEOUT)
                if clone_process.returncode != 0:
                    logger.error(f"Git clone failed: {stderr.decode('utf-8')}")
                    return False
            except subprocess.TimeoutExpired:
                logger.error(f"Git clone timed out after {GIT_OPERATION_TIMEOUT} seconds")
                clone_process.kill()
                
            return True
        except Exception as e:
            logger.error(f"Error cloning repository: {str(e)}")
            return False
    
    # 如果目录存在，检查是否是有效的Git仓库
    try:
        os.chdir(repo_path)
        is_git_repo = subprocess.run(
            "git rev-parse --is-inside-work-tree",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10  # 10秒超时
        ).returncode == 0
        
        if not is_git_repo:
            logger.warning(f"{repo_path} exists but is not a valid Git repository. Will remove and re-clone.")
            # 备份目录名
            backup_dir = f"{repo_path}_bak_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            os.rename(repo_path, backup_dir)
            # 重新克隆
            return ensure_repo_exists(repo_path, repo_url)
        
        # 如果是有效的Git仓库，更新它
        logger.info(f"Updating existing repository {repo_path}")
        try:
            # 先重置本地更改
            subprocess.run("git reset --hard HEAD", shell=True, check=True)
            # 使用fetch和reset而不是pull来更新
            subprocess.run("git fetch origin main", shell=True, check=True)
            subprocess.run("git reset --hard origin/main", shell=True, check=True)
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"Git operations timed out after {GIT_OPERATION_TIMEOUT} seconds")
            return False
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to update repository: {str(e)}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"Error checking repository: {str(e)}")
        return False

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
        try:
            # 使用fetch和reset替代pull
            subprocess.run("git fetch origin main", shell=True, check=True)
            subprocess.run("git reset --hard origin/main", shell=True, check=True)
        except subprocess.TimeoutExpired:
            logger.error(f"Git operations timed out in community repo after {GIT_OPERATION_TIMEOUT} seconds")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to update community repository: {str(e)}")
        
        total_plugins = 0
        processed_dirs = 0
        max_dirs = 500  # 设置最大处理目录数，防止无限循环
        
        # Skip these directories as they're not plugin directories
        skip_dirs = ['.git', '.github', '.assets', 'logs']
        
        # Get all immediate subdirectories (plugin author directories)
        author_dirs = []
        try:
            author_dirs = [d for d in os.listdir(repo_path) 
                          if os.path.isdir(os.path.join(repo_path, d)) 
                          and d not in skip_dirs 
                          and not d.startswith('.')]
        except Exception as e:
            logger.error(f"Error listing directories in {repo_path}: {str(e)}")
            return 0
            
        for author_dir in author_dirs:
            if processed_dirs >= max_dirs:
                logger.warning(f"Reached maximum directory limit ({max_dirs}). Stopping count.")
                break
                
            processed_dirs += 1
            author_path = os.path.join(repo_path, author_dir)
            
            # Skip non-directories and special directories
            if not os.path.isdir(author_path) or author_dir in skip_dirs or author_dir.startswith('.'):
                continue
            
            logger.info(f"Checking author directory: {author_dir}")
            
            try:
                # Check each plugin directory under the author
                plugin_dirs = []
                try:
                    plugin_dirs = [d for d in os.listdir(author_path) 
                                   if os.path.isdir(os.path.join(author_path, d))]
                except Exception as e:
                    logger.error(f"Error listing directories in {author_path}: {str(e)}")
                    continue
                    
                for plugin_dir in plugin_dirs:
                    plugin_path = os.path.join(author_path, plugin_dir)
                    
                    # Skip non-directories
                    if not os.path.isdir(plugin_path):
                        continue
                    
                    # Count subdirectories and .difypkg files in this plugin directory
                    has_subdirs = False
                    difypkg_count = 0
                    
                    try:
                        items = os.listdir(plugin_path)
                        for item in items:
                            item_path = os.path.join(plugin_path, item)
                            if os.path.isdir(item_path):
                                has_subdirs = True
                                total_plugins += 1
                                logger.info(f"  Found plugin subdirectory: {os.path.join(plugin_dir, item)}")
                            elif item.endswith('.difypkg'):
                                difypkg_count += 1
                    except Exception as e:
                        logger.error(f"Error processing plugin directory {plugin_path}: {str(e)}")
                        continue
                    
                    # If there are no subdirectories but there are .difypkg files, count as one plugin
                    if not has_subdirs and difypkg_count > 0:
                        total_plugins += 1
                        logger.info(f"  Found plugin with {difypkg_count} .difypkg files: {plugin_dir}")
            except Exception as e:
                logger.error(f"Error processing author directory {author_dir}: {str(e)}")
                continue
        
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
        try:
            # 使用fetch和reset替代pull
            subprocess.run("git fetch origin main", shell=True, check=True)
            subprocess.run("git reset --hard origin/main", shell=True, check=True)
        except subprocess.TimeoutExpired:
            logger.error(f"Git operations timed out in official repo after {GIT_OPERATION_TIMEOUT} seconds")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to update official repository: {str(e)}")
        
        total_plugins = 0
        plugin_categories = ['agent-strategies', 'extensions', 'models', 'tools', 'migrations']
        
        for category in plugin_categories:
            category_path = os.path.join(repo_path, category)
            if not os.path.isdir(category_path):
                continue
                
            logger.info(f"Checking official category: {category}")
            
            # Count each subdirectory as a plugin
            try:
                plugin_dirs = [d for d in os.listdir(category_path) 
                              if os.path.isdir(os.path.join(category_path, d))]
                              
                for plugin_dir in plugin_dirs:
                    plugin_path = os.path.join(category_path, plugin_dir)
                    if os.path.isdir(plugin_path):
                        total_plugins += 1
                        logger.info(f"  Found official plugin: {os.path.join(category, plugin_dir)}")
            except Exception as e:
                logger.error(f"Error processing category {category}: {str(e)}")
                continue
        
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
        
        # 添加超时设置
        response = requests.post(FEISHU_WEBHOOK, json=message, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            logger.info("Successfully sent message to Feishu")
        else:
            logger.error(f"Failed to send message to Feishu. Status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
    
    except requests.Timeout:
        logger.error(f"Timeout when sending message to Feishu (timeout={REQUEST_TIMEOUT}s)")
    except requests.ConnectionError:
        logger.error("Connection error when sending message to Feishu")
    except Exception as e:
        logger.error(f"Error sending message to Feishu: {str(e)}")

def main():
    # 设置资源限制
    try:
        set_resource_limits()
        logger.info("Resource limits set successfully")
    except Exception as e:
        logger.warning(f"Failed to set resource limits: {str(e)}")
    
    # 设置总体超时（15分钟）
    overall_timeout = 15 * 60  # 15分钟
    start_time = time.time()
    
    logger.info("Starting plugin count process")
    
    try:
        # Ensure repositories exist
        logger.info("Ensuring repositories exist...")
        community_repo_ok = ensure_repo_exists(DIFY_PLUGINS_REPO, "https://github.com/langgenius/dify-plugins.git")
        official_repo_ok = ensure_repo_exists(DIFY_OFFICIAL_PLUGINS_REPO, "https://github.com/langgenius/dify-official-plugins.git")
        
        if not community_repo_ok and not official_repo_ok:
            logger.error("Failed to ensure both repositories exist, aborting")
            return
        
        # 检查是否超时
        if time.time() - start_time > overall_timeout:
            logger.error("Process timed out after ensuring repositories")
            return
            
        # Count plugins
        logger.info("Counting plugins...")
        community_count = count_plugins_community(DIFY_PLUGINS_REPO) if community_repo_ok else 0
        
        # 再次检查是否超时
        if time.time() - start_time > overall_timeout:
            logger.error("Process timed out after counting community plugins")
            return
            
        official_count = count_plugins_official(DIFY_OFFICIAL_PLUGINS_REPO) if official_repo_ok else 0
        
        # Load history and calculate new plugins
        logger.info("Loading history and calculating new plugins...")
        history = load_history()
        community_new, official_new, total_new = calculate_new_plugins(history, community_count, official_count)
        save_history(history)
        
        # 发送通知前检查是否超时
        if time.time() - start_time > overall_timeout:
            logger.error("Process timed out before sending notification")
            return
            
        # 仅当成功获取到插件数量时才发送通知
        if community_count > 0 or official_count > 0:
            logger.info("Sending notification to Feishu...")
            try:
                send_to_feishu(community_count, official_count, community_new, official_new, total_new)
            except Exception as e:
                logger.error(f"Failed to send notification to Feishu: {str(e)}")
        else:
            logger.warning("Skipping Feishu notification because plugin count is zero")
    
    except Exception as e:
        logger.error(f"Unexpected error in main process: {str(e)}")
    finally:
        execution_time = time.time() - start_time
        logger.info(f"Finished plugin count process. Total execution time: {execution_time:.2f} seconds")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1) 