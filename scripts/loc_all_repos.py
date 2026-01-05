import os
import shutil
import subprocess
import json
import time

# Configuration from Environment Variables or Defaults
OWNER = os.environ.get("GITHUB_OWNER", "TheNewMikeMusic")
INCLUDE_FORKS = os.environ.get("INCLUDE_FORKS", "false").lower() == "true"
ORGS = os.environ.get("ORGS", "")  # Comma separated list of orgs
EXCLUDE_REPOS = os.environ.get("EXCLUDE_REPOS", "") # Comma separated list of repo names to exclude

CACHE_DIR = ".repos_cache"
LOC_START_MARKER = "<!-- LOC_START -->"
LOC_END_MARKER = "<!-- LOC_END -->"
README_FILE = "README.md"
# Standard excludes + others mentioned
EXCLUDES = "--exclude-dir=node_modules,dist,build,.next,.turbo,.git,.github,coverage,venv,.venv,target,out,.vercel,.idea,.vscode"

def run_command(cmd, cwd=None, env=None):
    # Pass current env (which includes GH_TOKEN) plus any overrides
    environ = os.environ.copy()
    if env:
        environ.update(env)
        
    result = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True, env=environ)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(result.stderr)
        return None
    return result.stdout.strip()

def get_repos_from_source(source_name, is_org=False):
    print(f"Fetching repositories for {source_name}...")
    limit = 1000
    # Include private repos by default with gh cli if token has access
    cmd = f'gh repo list {source_name} -L {limit} --json name,sshUrl,url,isFork,isArchived,visibility,owner'
    output = run_command(cmd)
    if not output:
        return []
    return json.loads(output)

def get_all_repos():
    all_repos = []
    
    # 1. Get Owner Repos
    owner_repos = get_repos_from_source(OWNER)
    all_repos.extend(owner_repos)
    
    # 2. Get Org Repos if defined
    if ORGS:
        org_list = [o.strip() for o in ORGS.split(",") if o.strip()]
        for org in org_list:
            org_repos = get_repos_from_source(org, is_org=True)
            all_repos.extend(org_repos)
            
    # Filter Repos
    excluded_names = [r.strip() for r in EXCLUDE_REPOS.split(",") if r.strip()]
    filtered_repos = []
    
    print(f"\nScanning {len(all_repos)} total candidates...")
    
    for repo in all_repos:
        full_name = f"{repo['owner']['login']}/{repo['name']}"
        
        # Filter Archived
        if repo.get('isArchived', False):
            continue
            
        # Filter Forks (unless opted in)
        if repo.get('isFork', False) and not INCLUDE_FORKS:
            continue
            
        # Filter Excluded Names
        if repo['name'] in excluded_names or full_name in excluded_names:
            print(f"Skipping excluded repo: {full_name}")
            continue
            
        filtered_repos.append(repo)
        
    # Deduplicate just in case
    unique_repos = {f"{r['owner']['login']}/{r['name']}": r for r in filtered_repos}.values()
    return list(unique_repos)

def clone_repos(repos):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR)
    
    print(f"\nCloning {len(repos)} repositories to {CACHE_DIR}...")
    
    for repo in repos:
        full_name = f"{repo['owner']['login']}/{repo['name']}"
        clone_path = os.path.join(CACHE_DIR, repo['owner']['login'], repo['name']) # Organize by owner/name to avoid collision
        
        print(f"Cloning {full_name} ({repo['visibility']})...")
        
        # Use gh repo clone which handles authentication automatically via GH_TOKEN env
        cmd = f'gh repo clone {full_name} "{clone_path}" -- --depth 1'
        run_command(cmd)

def count_loc_per_repo(repos):
    print("\nCounting lines of code per repo...")
    repo_stats = []
    global_stats = {} # Aggregate manually to ensure alignment
    
    languages_agg = {}
    total_code = 0
    
    for repo in repos:
        full_name = f"{repo['owner']['login']}/{repo['name']}"
        repo_path = os.path.join(CACHE_DIR, repo['owner']['login'], repo['name'])
        
        if not os.path.exists(repo_path):
            print(f"Warning: Path not found for {full_name}")
            continue
            
        cmd = f'cloc "{repo_path}" {EXCLUDES} --json'
        output = run_command(cmd)
        
        if output:
            try:
                stats = json.loads(output)
                # Repo sum
                code_lines = stats.get('SUM', {}).get('code', 0)
                repo_stats.append({'name': full_name, 'code': code_lines})
                
                print(f"  -> {full_name}: {code_lines} lines")
                total_code += code_lines
                
                # Aggregate languages
                for lang, data in stats.items():
                    if lang == 'header' or lang == 'SUM':
                        continue
                    if lang not in languages_agg:
                        languages_agg[lang] = 0
                    languages_agg[lang] += data['code']
                    
            except Exception as e:
                print(f"Error parsing cloc output for {full_name}: {e}")
    
    return repo_stats, languages_agg, total_code

def generate_markdown(repo_stats, languages_agg, total_code, repo_count):
    
    # Sort Languages
    sorted_langs = sorted(languages_agg.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Sort Repos
    sorted_repos = sorted(repo_stats, key=lambda x: x['code'], reverse=True)[:10]
    
    md_lines = []
    
    # 1. Overview
    md_lines.append(f"Repos scanned: **{repo_count}**" + (" (including forks)" if INCLUDE_FORKS else ""))
    md_lines.append(f"Total Lines of Code: **{total_code:,}**")
    md_lines.append(f"Last Updated: {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    md_lines.append("")
    
    # 2. Top Languages
    md_lines.append("#### Top Languages")
    md_lines.append("| Language | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for lang, count in sorted_langs:
        md_lines.append(f"| {lang} | {count:,} |")

    md_lines.append("")
    
    # 3. Top Repos
    md_lines.append("#### Top Repositories")
    md_lines.append("| Repository | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for repo in sorted_repos:
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
    print("README.md updated successfully.")

def main():
    print(f"--- LOC Scan Started for {OWNER} ---")
    print(f"Include Forks: {INCLUDE_FORKS}")
    print(f"Orgs: {ORGS}")
    
    repos = get_all_repos()
    
    repo_count = len(repos)
    print(f"\nFinal list of repositories to scan ({repo_count}):")
    for r in repos:
        print(f" - {r['owner']['login']}/{r['name']} ({r['visibility']})")
        
    if not repos:
        print("No repositories found to scan.")
        return

    clone_repos(repos)
    repo_stats, languages_agg, total_code = count_loc_per_repo(repos)
    
    print(f"\n--- Scan Complete ---")
    print(f"Total Lines: {total_code}")
    
    md_content = generate_markdown(repo_stats, languages_agg, total_code, repo_count)
    update_readme(md_content)
        
    # Cleanup
    if os.path.exists(CACHE_DIR):
        print("Cleaning up cache...")
        shutil.rmtree(CACHE_DIR)

if __name__ == "__main__":
    main()
