import os
import shutil
import subprocess
import json
import time

OWNER = "TheNewMikeMusic"
CACHE_DIR = ".repos_cache"
LOC_START_MARKER = "<!-- LOC_START -->"
LOC_END_MARKER = "<!-- LOC_END -->"
README_FILE = "README.md"
EXCLUDES = "--exclude-dir=node_modules,dist,build,.next,.git,.github,coverage,venv,.venv,target,out"

def run_command(cmd, cwd=None):
    result = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(result.stderr)
        return None
    return result.stdout.strip()

def get_repos():
    print("Fetching repository list...")
    # Get list of repos
    cmd = f'gh repo list {OWNER} -L 200 --json name,sshUrl,isFork,isArchived,defaultBranchRef'
    output = run_command(cmd)
    if not output:
        return []
    
    repos = json.loads(output)
    filtered_repos = []
    
    for repo in repos:
        if repo.get('isFork', False) or repo.get('isArchived', False):
            continue
        filtered_repos.append(repo)
        
    return filtered_repos

def clone_repos(repos):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR)
    
    print(f"Cloning {len(repos)} repositories to {CACHE_DIR}...")
    
    for repo in repos:
        name = repo['name']
        print(f"Cloning {name}...")
        # Shallow clone single branch
        cmd = f'gh repo clone {OWNER}/{name} {CACHE_DIR}/{name} -- --depth 1'
        run_command(cmd)

def count_loc_global():
    print("Counting global lines of code...")
    cmd = f'cloc {CACHE_DIR} {EXCLUDES} --json'
    output = run_command(cmd)
    if not output:
        return None
    return json.loads(output)

def count_loc_per_repo(repos):
    print("Counting lines of code per repo...")
    repo_stats = []
    
    for repo in repos:
        name = repo['name']
        repo_path = os.path.join(CACHE_DIR, name)
        if not os.path.exists(repo_path):
            continue
            
        cmd = f'cloc {repo_path} {EXCLUDES} --json'
        output = run_command(cmd)
        if output:
            try:
                stats = json.loads(output)
                code_lines = stats.get('SUM', {}).get('code', 0)
                repo_stats.append({'name': name, 'code': code_lines})
            except:
                pass
                
    return repo_stats

def generate_markdown(global_stats, repo_stats, repo_count):
    if not global_stats:
        return "Could not calculate stats."
    
    sum_stats = global_stats.get('SUM', {})
    total_lines = sum_stats.get('code', 0)
    
    # Sort languages by code count
    languages = []
    for key, value in global_stats.items():
        if key == 'header' or key == 'SUM':
            continue
        languages.append({'name': key, 'code': value['code']})
    
    languages.sort(key=lambda x: x['code'], reverse=True)
    top_langs = languages[:10]
    
    # Sort repos by code count
    repo_stats.sort(key=lambda x: x['code'], reverse=True)
    top_repos = repo_stats[:10]
    
    md_lines = []
    md_lines.append(f"Repos scanned: **{repo_count}**")
    md_lines.append(f"Total Lines of Code: **{total_lines:,}**")
    md_lines.append(f"Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    md_lines.append("")
    md_lines.append("#### Top Languages")
    md_lines.append("| Language | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for lang in top_langs:
        md_lines.append(f"| {lang['name']} | {lang['code']:,} |")

    md_lines.append("")
    md_lines.append("#### Top Repositories")
    md_lines.append("| Repository | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for repo in top_repos:
        md_lines.append(f"| {repo['name']} | {repo['code']:,} |")
        
    return "\n".join(md_lines)

def update_readme(content):
    if not os.path.exists(README_FILE):
        print(f"{README_FILE} not found.")
        return

    with open(README_FILE, 'r', encoding='utf-8') as f:
        readme_content = f.read()

    start_idx = readme_content.find(LOC_START_MARKER)
    end_idx = readme_content.find(LOC_END_MARKER)

    if start_idx == -1 or end_idx == -1:
        print("Markers not found in README.md")
        return

    new_content = (
        readme_content[:start_idx + len(LOC_START_MARKER)] + "\n" +
        content + "\n" +
        readme_content[end_idx:]
    )

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("README.md updated.")

def main():
    repos = get_repos()
    print(f"Found {len(repos)} repositories to scan.")
    
    if not repos:
        print("No repositories found.")
        return

    clone_repos(repos)
    global_stats = count_loc_global()
    repo_stats = count_loc_per_repo(repos)
    
    if global_stats:
        md_content = generate_markdown(global_stats, repo_stats, len(repos))
        print("Generated Stats:")
        print(md_content)
        update_readme(md_content)
        
    # Cleanup
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)

if __name__ == "__main__":
    main()
