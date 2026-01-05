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
INCLUDE_JSON_IN_ENG = os.environ.get("INCLUDE_JSON_IN_ENG", "false").lower() == "true"
EXCLUDE_EXTS = os.environ.get("EXCLUDE_EXTS", "")

CACHE_DIR = ".repos_cache"
LOC_START_MARKER = "<!-- LOC_START -->"
LOC_END_MARKER = "<!-- LOC_END -->"
README_FILE = "README.md"

# Standard noisy directories
EXCLUDE_DIRS = "node_modules,dist,build,.next,.turbo,.git,.github,coverage,venv,.venv,target,out,.vercel,.idea,.vscode,bin,obj"
# Standard lockfiles and noisy files to exclude from all counts
EXCLUDE_FILES = "package-lock.json,yarn.lock,pnpm-lock.yaml,bun.lockb,composer.lock,Podfile.lock,mix.lock"

def run_command(cmd, cwd=None, env=None):
    environ = os.environ.copy()
    if env:
        environ.update(env)
    
    result = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True, env=environ)
    if result.returncode != 0:
        return None
    return result.stdout.strip()

def get_all_repos():
    print(f"Fetching repository list for {OWNER}...")
    all_repos = []
    
    # Fetch Public
    cmd_public = f'gh repo list {OWNER} --visibility public -L 1000 --json nameWithOwner,name,isFork,isArchived,visibility'
    output_public = run_command(cmd_public)
    if output_public:
        all_repos.extend(json.loads(output_public))

    # Fetch Private
    cmd_private = f'gh repo list {OWNER} --visibility private -L 1000 --json nameWithOwner,name,isFork,isArchived,visibility'
    output_private = run_command(cmd_private)
    if output_private:
        all_repos.extend(json.loads(output_private))
            
    # Deduplicate
    seen = set()
    unique_repos = []
    for r in all_repos:
        if r['nameWithOwner'] not in seen:
            seen.add(r['nameWithOwner'])
            unique_repos.append(r)
        
    return unique_repos

def filter_repos(all_repos):
    excluded_names = [r.strip() for r in EXCLUDE_REPOS.split(",") if r.strip()]
    filtered_repos = []
    
    for repo in all_repos:
        full_name = repo['nameWithOwner']
        if repo.get('isArchived', False): continue
        if repo.get('isFork', False) and not INCLUDE_FORKS: continue
        if repo['name'] in excluded_names or full_name in excluded_names: continue
        filtered_repos.append(repo)
    return filtered_repos

def get_safe_path(repo):
    safe_name = repo['nameWithOwner'].replace('/', '__')
    return os.path.join(CACHE_DIR, safe_name)

def clone_repos(repos):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR)
    
    print(f"Cloning {len(repos)} repositories...")
    for repo in repos:
        full_name = repo['nameWithOwner']
        clone_path = get_safe_path(repo)
        cmd = f'gh repo clone {full_name} "{clone_path}" -- --depth 1'
        run_command(cmd)

def count_loc(repos):
    print("Analyzing code volume (Dual Metric)...")
    repo_stats = []
    languages_agg_total = {}
    languages_agg_eng = {}
    global_total_loc = 0
    global_eng_loc = 0
    
    # Extension exclusions
    user_exclude_exts = [e.strip() for e in EXCLUDE_EXTS.split(",") if e.strip()]
    
    for repo in repos:
        full_name = repo['nameWithOwner']
        repo_path = get_safe_path(repo)
        if not os.path.exists(repo_path): continue
            
        # Standard cloc command excluding noise
        cloc_base = f'cloc "{repo_path}" --exclude-dir={EXCLUDE_DIRS} --not-match-f="({EXCLUDE_FILES.replace(",","|")})"'
        
        # User defined exts
        if user_exclude_exts:
            cloc_base += f' --exclude-ext={",".join(user_exclude_exts)}'

        output = run_command(cloc_base + " --json")
        
        if output:
            try:
                stats = json.loads(output)
                repo_total = stats.get('SUM', {}).get('code', 0)
                repo_eng = 0
                
                # Per-language breakdown for English LOC filtering
                for lang, data in stats.items():
                    if lang in ['header', 'SUM']: continue
                    
                    code = data['code']
                    # Total aggregating
                    languages_agg_total[lang] = languages_agg_total.get(lang, 0) + code
                    
                    # Engineering Filter: Exclude JSON unless forced
                    is_json = lang.lower() == 'json'
                    if not is_json or INCLUDE_JSON_IN_ENG:
                        repo_eng += code
                        languages_agg_eng[lang] = languages_agg_eng.get(lang, 0) + code
                
                repo_stats.append({
                    'name': repo['name'], 
                    'eng_code': repo_eng, 
                    'total_code': repo_total
                })
                global_total_loc += repo_total
                global_eng_loc += repo_eng
                
            except: continue
                
    return repo_stats, languages_agg_total, global_total_loc, global_eng_loc

def generate_markdown(repo_stats, languages_agg_total, global_total_loc, global_eng_loc, scanned_count):
    # Sort repos by Engineering LOC
    sorted_repos = sorted(repo_stats, key=lambda x: x['eng_code'], reverse=True)
    # Sort langs by Total LOC for the distribution
    sorted_langs = sorted(languages_agg_total.items(), key=lambda x: x[1], reverse=True)
    
    current_time = time.strftime('%Y-%m-%d %H:%M', time.gmtime())
    
    md = []
    md.append("LOC by cloc. Engineering LOC excludes lockfiles & generated assets.")
    md.append("")
    
    # Compact Dashboard
    md.append(f"**Repositories:** {scanned_count}  |  **Engineering LOC:** {global_eng_loc:,}  |  **Total LOC:** {global_total_loc:,} (incl config/data)  |  **Sync:** {current_time} UTC")
    md.append("")
    
    # Language Distribution (Top 6 visible)
    md.append("#### Language Distribution")
    md.append("| Language | LOC |")
    md.append("| :--- | :--- |")
    for lang, count in sorted_langs[:6]:
        md.append(f"| {lang} | {count:,} |")
    
    # Top Repos (Top 5)
    md.append("\n#### Technical Depth by Repository")
    md.append("| Repository | Engineering LOC | Total LOC |")
    md.append("| :--- | :--- | :--- |")
    for repo in sorted_repos[:5]:
        md.append(f"| `{repo['name']}` | {repo['eng_code']:,} | {repo['total_code']:,} |")
    
    # Collapsible Details
    md.append("\n<details>")
    md.append("<summary>More details</summary>")
    md.append("\n#### Full Language Breakdown")
    md.append("| Language | LOC |")
    md.append("| :--- | :--- |")
    for lang, count in sorted_langs:
        md.append(f"| {lang} | {count:,} |")
        
    md.append("\n#### Full Repository Index")
    md.append("| Repository | Engineering LOC | Total LOC |")
    md.append("| :--- | :--- | :--- |")
    for repo in sorted_repos:
        md.append(f"| `{repo['name']}` | {repo['eng_code']:,} | {repo['total_code']:,} |")
    
    md.append("</details>")
    
    return "\n".join(md)

def update_readme(content):
    if not os.path.exists(README_FILE): return
    with open(README_FILE, 'r', encoding='utf-8') as f:
        readme = f.read()

    start_idx = readme.find(LOC_START_MARKER)
    end_idx = readme.find(LOC_END_MARKER)
    if start_idx == -1 or end_idx == -1: return

    new_readme = (
        readme[:start_idx + len(LOC_START_MARKER)] + "\n" +
        content + "\n" +
        readme[end_idx:]
    )

    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(new_readme)

def main():
    print("--- LOC Intelligence v5.0 (Credible Metrics) ---")
    all_repos = get_all_repos()
    repos = filter_repos(all_repos)
    if not repos:
        print("No repositories found.")
        sys.exit(0)

    clone_repos(repos)
    repo_stats, languages_agg, total_loc, eng_loc = count_loc(repos)
    
    md_content = generate_markdown(repo_stats, languages_agg, total_loc, eng_loc, len(repos))
    update_readme(md_content)
    
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)

if __name__ == "__main__":
    main()
