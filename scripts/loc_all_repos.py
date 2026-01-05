import os
import shutil
import subprocess
import json
import time
import sys

# Configuration
OWNER = os.environ.get("GITHUB_OWNER", "TheNewMikeMusic")
INCLUDE_FORKS = os.environ.get("INCLUDE_FORKS", "false").lower() == "true"
EXCLUDE_REPOS = os.environ.get("EXCLUDE_REPOS", "")

CACHE_DIR = ".repos_cache"
LOC_START_MARKER = "<!-- LOC_START -->"
LOC_END_MARKER = "<!-- LOC_END -->"
README_FILE = "README.md"
EXCLUDES = "--exclude-dir=node_modules,dist,build,.next,.turbo,.git,.github,coverage,venv,.venv,target,out,.vercel,.idea,.vscode,bin,obj"

def run_command(cmd, cwd=None, env=None):
    environ = os.environ.copy()
    if env:
        environ.update(env)
    
    print(f"DEBUG: Running command: {cmd}")
    # Capture output and suppress stderr unless error
    result = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True, env=environ)
    if result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}")
        print(f"ERROR STDERR: {result.stderr}")
        return None
    return result.stdout.strip()

def get_all_repos():
    print(f"Fetching all repositories...")
    all_repos = []
    
    # Fetch Public
    print("Fetching public repositories...")
    cmd_public = f'gh repo list {OWNER} --visibility public -L 1000 --json nameWithOwner,name,isFork,isArchived,visibility,sshUrl,url'
    output_public = run_command(cmd_public)
    if output_public:
        try:
            all_repos.extend(json.loads(output_public))
        except json.JSONDecodeError:
            print("Error decoding JSON from public repos")

    # Fetch Private
    print("Fetching private repositories...")
    cmd_private = f'gh repo list {OWNER} --visibility private -L 1000 --json nameWithOwner,name,isFork,isArchived,visibility,sshUrl,url'
    output_private = run_command(cmd_private)
    if output_private:
        try:
            all_repos.extend(json.loads(output_private))
        except json.JSONDecodeError:
            print("Error decoding JSON from private repos")
            
    # Deduplicate (just in case repo appears in both or multiple calls confusingly)
    seen = set()
    unique_repos = []
    for r in all_repos:
        if r['nameWithOwner'] not in seen:
            seen.add(r['nameWithOwner'])
            unique_repos.append(r)

    if not unique_repos:
        print("CRITICAL ERROR: Failed to fetch (or found zero) repositories. Check GH_PAT permissions.")
        # We don't exit here immediately to allow "0 repos" scenario if truly empty, 
        # but combined with main() check it will handle it.
        
    return unique_repos

def filter_repos(all_repos):
    excluded_names = [r.strip() for r in EXCLUDE_REPOS.split(",") if r.strip()]
    filtered_repos = []
    print(f"\nTotal repos visible to token: {len(all_repos)}")
    
    for repo in all_repos:
        full_name = repo['nameWithOwner']
        # Filter Archived
        if repo.get('isArchived', False):
            continue
        # Filter Forks
        if repo.get('isFork', False) and not INCLUDE_FORKS:
            continue
        # Filter Excluded Names
        if repo['name'] in excluded_names or full_name in excluded_names:
            print(f"Skipping excluded repo: {full_name}")
            continue
        filtered_repos.append(repo)
    return filtered_repos

def get_safe_path(repo):
    safe_name = repo['nameWithOwner'].replace('/', '__')
    return os.path.join(CACHE_DIR, safe_name)

def clone_repos(repos):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR)
    
    print(f"\nCloning {len(repos)} repositories...")
    
    for repo in repos:
        full_name = repo['nameWithOwner']
        clone_path = get_safe_path(repo)
        
        print(f"Cloning {full_name} ({repo['visibility']})...")
        cmd = f'gh repo clone {full_name} "{clone_path}" -- --depth 1'
        res = run_command(cmd)
        if res is None:
             print(f"WARNING: Failed to clone {full_name}. Skipping.")

def count_loc(repos):
    print("\nCounting lines of code per repo...")
    repo_stats = []
    languages_agg = {}
    total_code = 0
    
    print(f"{'Repository':<40} | {'LOC':<10}")
    print("-" * 55)
    
    for repo in repos:
        full_name = repo['nameWithOwner']
        repo_path = get_safe_path(repo)
        
        if not os.path.exists(repo_path):
            continue
            
        cmd = f'cloc "{repo_path}" {EXCLUDES} --json'
        output = run_command(cmd)
        
        if output:
            try:
                stats = json.loads(output)
                code_lines = stats.get('SUM', {}).get('code', 0)
                repo_stats.append({'name': full_name, 'code': code_lines})
                
                print(f"{full_name:<40} | {code_lines:<10}")
                total_code += code_lines
                
                for lang, data in stats.items():
                    if lang == 'header' or lang == 'SUM':
                        continue
                    if lang not in languages_agg:
                        languages_agg[lang] = 0
                    languages_agg[lang] += data['code']
                    
            except Exception as e:
                print(f"Error parsing cloc output for {full_name}: {e}")
                
    print("-" * 55)
    print(f"{'TOTAL':<40} | {total_code:<10}")
    return repo_stats, languages_agg, total_code

def generate_markdown(repo_stats, languages_agg, total_code, visible_count, scanned_count):
    # Sort Languages
    sorted_langs = sorted(languages_agg.items(), key=lambda x: x[1], reverse=True)[:10]
    # Sort Repos
    sorted_repos = sorted(repo_stats, key=lambda x: x['code'], reverse=True)
    
    current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    
    md_lines = []
    
    # 1. Cleaner Metric Summary
    md_lines.append(f"📦 **Repos Scanned:** {scanned_count}  ·  🚀 **Total Lines of Code:** {total_code:,}  ·  🕒 **Updated:** {current_time} UTC")
    md_lines.append("")
    
    # 2. Compact Top Languages Table
    md_lines.append("#### 📊 Top Languages")
    md_lines.append("| Language | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for lang, count in sorted_langs:
        md_lines.append(f"| {lang} | {count:,} |")
    md_lines.append("")
    
    # 3. Refined Top Repos (Show Top 5, hide rest)
    md_lines.append("#### 🏆 Top Repositories")
    
    top_5 = sorted_repos[:5]
    md_lines.append("| Repository | Code Lines |")
    md_lines.append("| :--- | :--- |")
    for repo in top_5:
        md_lines.append(f"| `{repo['name']}` | {repo['code']:,} |")
    
    if len(sorted_repos) > 5:
        md_lines.append("")
        md_lines.append("<details>")
        md_lines.append("<summary>📑 Show more repositories</summary>")
        md_lines.append("")
        md_lines.append("| Repository | Code Lines |")
        md_lines.append("| :--- | :--- |")
        for repo in sorted_repos[5:]:
            md_lines.append(f"| `{repo['name']}` | {repo['code']:,} |")
        md_lines.append("")
        md_lines.append("</details>")
        
    return "\n".join(md_lines)

def ensure_readme_structure():
    if not os.path.exists(README_FILE):
        return

    with open(README_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
        
    if LOC_START_MARKER not in content:
        print(f"Adding stats block to {README_FILE}...")
        with open(README_FILE, 'a', encoding='utf-8') as f:
            f.write("\n\n### Codebase Stats\n")
            f.write(f"{LOC_START_MARKER}\n(Updating...)\n{LOC_END_MARKER}\n")

def update_readme(content):
    ensure_readme_structure()
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
    print(f"--- LOC Scan Started v3.0 (Premium Layout) ---")
    print(f"Owner: {OWNER}")
    
    # 1. Get All Repos
    all_repos = get_all_repos()
    visible_count = len(all_repos)
    print(f"Successfully fetched {visible_count} repositories.")
    
    # 2. Filter
    repos = filter_repos(all_repos)
    scanned_count = len(repos)
    
    if not repos:
        print("WARNING: No repositories found after filtering.")
        # We still want to update README to say "0" maybe? Or just exit.
        # But if visible_count > 0, we should probably proceed.
        if visible_count == 0:
            print("CRITICAL: Token sees 0 repos. Check permissions.")
            sys.exit(1)

    # 3. Clone & Count
    clone_repos(repos)
    repo_stats, languages_agg, total_code = count_loc(repos)
    
    # 4. Generate & Update
    md_content = generate_markdown(repo_stats, languages_agg, total_code, visible_count, scanned_count)
    update_readme(md_content)
        
    # Cleanup
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)

if __name__ == "__main__":
    main()
