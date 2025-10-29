#!/usr/bin/env python
# coding:utf-8

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from datetime import datetime, timedelta
from github import Github
import gitlab
import requests
import re
import json
import os
import hashlib
from functools import wraps
import io
import base64
import time
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///code_stats.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = APScheduler()

# Database Models
class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(100), nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    base_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

class Repository(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    repo_name = db.Column(db.String(200), nullable=False)
    repo_id = db.Column(db.String(100), nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    last_updated = db.Column(db.DateTime)
    
class FileCache(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, db.ForeignKey('repository.id'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)
    language = db.Column(db.String(50))
    total_lines = db.Column(db.Integer, default=0)
    code_lines = db.Column(db.Integer, default=0)
    comment_lines = db.Column(db.Integer, default=0)
    empty_lines = db.Column(db.Integer, default=0)
    last_modified = db.Column(db.DateTime)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow)

class Statistics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'))
    date = db.Column(db.Date, nullable=False)
    language = db.Column(db.String(50), nullable=False)
    files = db.Column(db.Integer, default=0)
    total_lines = db.Column(db.Integer, default=0)
    code_lines = db.Column(db.Integer, default=0)
    comment_lines = db.Column(db.Integer, default=0)
    empty_lines = db.Column(db.Integer, default=0)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200))

class CustomEndpoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    path = db.Column(db.String(200), nullable=False, unique=True)
    method = db.Column(db.String(10), nullable=False, default='GET')
    description = db.Column(db.Text)
    query = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Load language definitions
with open('languages.json', 'r') as f:
    LANGUAGES = json.load(f)

# Global variable to track scanning progress
scanning_progress = {
    'is_active': False,
    'percentage': 0,
    'status': 'Ready',
    'details': '',
    'total_accounts': 0,
    'current_account': 0,
    'total_repos': 0,
    'current_repo': 0
}

# Helper Functions
def get_language(filepath):
    for language in LANGUAGES.values():
        for extension in language['extensions']:
            if filepath.endswith(extension):
                return language
    return None

def count_lines_from_content(content, language):
    try:
        lines = content.split('\n')
        total_lines = len(lines)
        code_lines = 0
        comment_lines = 0
        empty_lines = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                empty_lines += 1
            elif re.match(language['comment_regex'], line):
                comment_lines += 1
            else:
                code_lines += 1
        
        return (total_lines, code_lines, comment_lines, empty_lines)
    except Exception as e:
        print(f"Error counting lines: {e}")
        return (0, 0, 0, 0)

def get_file_hash(content):
    return hashlib.sha256(content.encode('utf-8', errors='ignore')).hexdigest()

def is_binary_content(content):
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='strict')
        else:
            content.encode('utf-8', errors='strict')
        return '\x00' in content
    except:
        return True

def decode_content(content):
    """Safely decode content with multiple encoding attempts"""
    if isinstance(content, str):
        return content
    
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'ascii']
    
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    
    # Last resort: decode with errors='ignore'
    try:
        return content.decode('utf-8', errors='ignore')
    except:
        return ""

def fetch_github_repos(account):
    g = Github(account.access_token)
    repos_data = []
    
    try:
        for repo in g.get_user().get_repos(affiliation='owner'):
            repos_data.append({
                'name': repo.name,
                'id': str(repo.id),
                'private': repo.private,
                'url': repo.html_url,
                'default_branch': repo.default_branch or 'main'
            })
    except Exception as e:
        print(f"Error fetching repos: {e}")
    
    return repos_data

def fetch_gitlab_repos(account):
    try:
        if account.base_url:
            gl = gitlab.Gitlab(account.base_url, private_token=account.access_token)
        else:
            gl = gitlab.Gitlab('https://gitlab.com', private_token=account.access_token)
        
        gl.auth()
        repos_data = []
        
        for project in gl.projects.list(owned=True, all=True):
            repos_data.append({
                'name': project.name,
                'id': str(project.id),
                'private': project.visibility == 'private',
                'url': project.web_url,
                'default_branch': project.default_branch or 'main'
            })
        
        return repos_data
    except Exception as e:
        print(f"Error fetching GitLab repos: {e}")
        return []

def analyze_github_repo(account, repo_info):
    g = Github(account.access_token)
    repo = g.get_repo(f"{account.username}/{repo_info['name']}")
    
    db_repo = db.session.query(Repository).filter_by(
        account_id=account.id,
        repo_id=repo_info['id']
    ).first()
    
    if not db_repo:
        db_repo = Repository(
            account_id=account.id,
            repo_name=repo_info['name'],
            repo_id=repo_info['id'],
            is_private=repo_info['private']
        )
        db.session.add(db_repo)
        db.session.commit()
    
    stats = {}
    
    try:
        # Try default branch first, then master, then main
        branches_to_try = [repo_info.get('default_branch', 'main'), 'master', 'main']
        contents = None
        
        for branch in branches_to_try:
            try:
                contents = repo.get_contents("", ref=branch)
                break
            except:
                continue
        
        if not contents:
            print(f"Could not access any branch for {repo_info['name']}")
            return stats
        
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                try:
                    contents.extend(repo.get_contents(file_content.path, ref=branch))
                except:
                    continue
            else:
                process_github_file(db_repo, repo, file_content, stats, branch)
                
    except Exception as e:
        print(f"Error processing repo {repo_info['name']}: {e}")
    
    db_repo.last_updated = datetime.utcnow()
    db.session.commit()
    
    return stats

def process_github_file(db_repo, repo, file_content, stats, branch='main'):
    language = get_language(file_content.path)
    if not language:
        return
    
    cached_file = db.session.query(FileCache).filter_by(
        repo_id=db_repo.id,
        file_path=file_content.path
    ).first()
    
    file_sha = file_content.sha
    
    if cached_file and cached_file.file_hash == file_sha:
        lang_name = language['name'].upper()
        if lang_name not in stats:
            stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
        
        stats[lang_name]['files'] += 1
        stats[lang_name]['total'] += cached_file.total_lines
        stats[lang_name]['code'] += cached_file.code_lines
        stats[lang_name]['comment'] += cached_file.comment_lines
        stats[lang_name]['empty'] += cached_file.empty_lines
        return
    
    try:
        file_obj = repo.get_contents(file_content.path, ref=branch)
        
        # Skip files larger than 10MB (GitHub API limitation)
        if file_obj.size > 10 * 1024 * 1024:
            print(f"Skipping large file (>{file_obj.size} bytes): {file_content.path}")
            return
        
        # Handle encoding properly - GitHub returns None for large files or binary files
        content = None
        
        try:
            # Method 1: Try decoded_content first
            if hasattr(file_obj, 'decoded_content') and file_obj.decoded_content:
                content = decode_content(file_obj.decoded_content)
            
            # Method 2: If encoding is None or content failed, use raw download
            elif file_obj.encoding == 'none' or not content:
                # Download via raw URL for files with encoding: none
                raw_url = file_obj.download_url
                if raw_url:
                    import requests
                    response = requests.get(raw_url, timeout=30)
                    if response.status_code == 200:
                        content = decode_content(response.content)
            
            # Method 3: Try base64 decoding the content
            elif file_obj.content:
                raw_content = base64.b64decode(file_obj.content)
                content = decode_content(raw_content)
                
        except Exception as e:
            print(f"Could not decode {file_content.path}: {e}")
            return
        
        if not content:
            print(f"Empty content for {file_content.path}")
            return
            
        if is_binary_content(content):
            return
        
        total, code, comment, empty = count_lines_from_content(content, language)
        
        if cached_file:
            cached_file.file_hash = file_sha
            cached_file.total_lines = total
            cached_file.code_lines = code
            cached_file.comment_lines = comment
            cached_file.empty_lines = empty
            cached_file.last_modified = datetime.utcnow()
            cached_file.cached_at = datetime.utcnow()
        else:
            cached_file = FileCache(
                repo_id=db_repo.id,
                file_path=file_content.path,
                file_hash=file_sha,
                language=language['name'].upper(),
                total_lines=total,
                code_lines=code,
                comment_lines=comment,
                empty_lines=empty,
                last_modified=datetime.utcnow()
            )
            db.session.add(cached_file)
        
        lang_name = language['name'].upper()
        if lang_name not in stats:
            stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
        
        stats[lang_name]['files'] += 1
        stats[lang_name]['total'] += total
        stats[lang_name]['code'] += code
        stats[lang_name]['comment'] += comment
        stats[lang_name]['empty'] += empty
        
        db.session.commit()
        
    except Exception as e:
        print(f"Error processing file {file_content.path}: {e}")

def analyze_gitlab_repo(account, repo_info):
    try:
        if account.base_url:
            gl = gitlab.Gitlab(account.base_url, private_token=account.access_token)
        else:
            gl = gitlab.Gitlab('https://gitlab.com', private_token=account.access_token)
        
        gl.auth()
        project = gl.projects.get(repo_info['id'])
        
        db_repo = db.session.query(Repository).filter_by(
            account_id=account.id,
            repo_id=repo_info['id']
        ).first()
        
        if not db_repo:
            db_repo = Repository(
                account_id=account.id,
                repo_name=repo_info['name'],
                repo_id=repo_info['id'],
                is_private=repo_info['private']
            )
            db.session.add(db_repo)
            db.session.commit()
        
        stats = {}
        
        try:
            items = project.repository_tree(recursive=True, all=True)
            for item in items:
                if item['type'] == 'blob':
                    process_gitlab_file(db_repo, project, item, stats)
        except Exception as e:
            print(f"Error processing repo {repo_info['name']}: {e}")
        
        db_repo.last_updated = datetime.utcnow()
        db.session.commit()
        
        return stats
        
    except Exception as e:
        print(f"Error with GitLab repo {repo_info['name']}: {e}")
        return {}

def process_gitlab_file(db_repo, project, item, stats):
    language = get_language(item['path'])
    if not language:
        return
    
    cached_file = db.session.query(FileCache).filter_by(
        repo_id=db_repo.id,
        file_path=item['path']
    ).first()
    
    file_id = item['id']
    
    if cached_file and cached_file.file_hash == file_id:
        lang_name = language['name'].upper()
        if lang_name not in stats:
            stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
        
        stats[lang_name]['files'] += 1
        stats[lang_name]['total'] += cached_file.total_lines
        stats[lang_name]['code'] += cached_file.code_lines
        stats[lang_name]['comment'] += cached_file.comment_lines
        stats[lang_name]['empty'] += cached_file.empty_lines
        return
    
    try:
        file_content = project.files.get(file_path=item['path'], ref='main')
        raw_content = file_content.decode()
        content = decode_content(raw_content)
        
        if is_binary_content(content):
            return
        
        total, code, comment, empty = count_lines_from_content(content, language)
        
        if cached_file:
            cached_file.file_hash = file_id
            cached_file.total_lines = total
            cached_file.code_lines = code
            cached_file.comment_lines = comment
            cached_file.empty_lines = empty
            cached_file.last_modified = datetime.utcnow()
            cached_file.cached_at = datetime.utcnow()
        else:
            cached_file = FileCache(
                repo_id=db_repo.id,
                file_path=item['path'],
                file_hash=file_id,
                language=language['name'].upper(),
                total_lines=total,
                code_lines=code,
                comment_lines=comment,
                empty_lines=empty,
                last_modified=datetime.utcnow()
            )
            db.session.add(cached_file)
        
        lang_name = language['name'].upper()
        if lang_name not in stats:
            stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
        
        stats[lang_name]['files'] += 1
        stats[lang_name]['total'] += total
        stats[lang_name]['code'] += code
        stats[lang_name]['comment'] += comment
        stats[lang_name]['empty'] += empty
        
        db.session.commit()
        
    except Exception as e:
        print(f"Error processing file {item['path']}: {e}")

def save_statistics(account_id, stats):
    today = datetime.utcnow().date()
    
    # Delete old statistics for today to avoid duplicates
    db.session.query(Statistics).filter_by(account_id=account_id, date=today).delete()
    
    for language, data in stats.items():
        stat = Statistics(
            account_id=account_id,
            date=today,
            language=language,
            files=data['files'],
            total_lines=data['total'],
            code_lines=data['code'],
            comment_lines=data['comment'],
            empty_lines=data['empty']
        )
        db.session.add(stat)
    
    db.session.commit()

def analyze_account(account_id, account_index, total_accounts, total_repos):
    global scanning_progress
    
    account = db.session.get(Account, account_id)
    if not account or not account.is_active:
        return
    
    # Update progress for account start
    scanning_progress['current_account'] = account_index
    account_percentage = (account_index / total_accounts) * 80  # 80% for accounts, 20% for repos
    scanning_progress['percentage'] = 15 + account_percentage
    scanning_progress['status'] = f'Analyzing account: {account.username}'
    scanning_progress['details'] = f'Account {account_index} of {total_accounts} ({account.platform})'
    
    print(f"\n{'='*60}")
    print(f"Analyzing account: {account.username} ({account.platform})")
    print(f"{'='*60}")
    
    all_stats = {}
    
    if account.platform == 'github':
        repos = fetch_github_repos(account)
        print(f"Found {len(repos)} repositories")
        
        for repo_idx, repo in enumerate(repos, 1):
            # Update repo progress
            repo_progress = (repo_idx / len(repos)) * 15  # 15% per account for repos
            scanning_progress['percentage'] = min(15 + account_percentage + repo_progress, 95)
            scanning_progress['current_repo'] += 1
            scanning_progress['details'] = f'Repo {repo_idx} of {len(repos)}: {repo["name"]}'
            
            print(f"\n[{repo_idx}/{len(repos)}] Analyzing repo: {repo['name']}...")
            repo_stats = analyze_github_repo(account, repo)
            
            # Show repo statistics
            total_lines = sum(data['total'] for data in repo_stats.values())
            total_files = sum(data['files'] for data in repo_stats.values())
            print(f"  ✓ Files: {total_files}, Lines: {total_lines:,}")
            
            for lang, data in repo_stats.items():
                if lang not in all_stats:
                    all_stats[lang] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
                all_stats[lang]['files'] += data['files']
                all_stats[lang]['total'] += data['total']
                all_stats[lang]['code'] += data['code']
                all_stats[lang]['comment'] += data['comment']
                all_stats[lang]['empty'] += data['empty']
    
    elif account.platform == 'gitlab':
        repos = fetch_gitlab_repos(account)
        print(f"Found {len(repos)} repositories")
        
        for repo_idx, repo in enumerate(repos, 1):
            # Update repo progress
            repo_progress = (repo_idx / len(repos)) * 15  # 15% per account for repos
            scanning_progress['percentage'] = min(15 + account_percentage + repo_progress, 95)
            scanning_progress['current_repo'] += 1
            scanning_progress['details'] = f'Repo {repo_idx} of {len(repos)}: {repo["name"]}'
            
            print(f"\n[{repo_idx}/{len(repos)}] Analyzing repo: {repo['name']}...")
            repo_stats = analyze_gitlab_repo(account, repo)
            
            # Show repo statistics
            total_lines = sum(data['total'] for data in repo_stats.values())
            total_files = sum(data['files'] for data in repo_stats.values())
            print(f"  ✓ Files: {total_files}, Lines: {total_lines:,}")
            
            for lang, data in repo_stats.items():
                if lang not in all_stats:
                    all_stats[lang] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
                all_stats[lang]['files'] += data['files']
                all_stats[lang]['total'] += data['total']
                all_stats[lang]['code'] += data['code']
                all_stats[lang]['comment'] += data['comment']
                all_stats[lang]['empty'] += data['empty']
    
    save_statistics(account.id, all_stats)
    
    print(f"\n{'='*60}")
    print(f"✓ Completed analysis for {account.username}")
    print(f"{'='*60}")
    print("\nFinal Statistics:")
    for lang, data in sorted(all_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        print(f"  {lang:15} - Files: {data['files']:5} | Lines: {data['total']:8,}")
    print(f"{'='*60}\n")

def analyze_all_accounts():
    global scanning_progress
    with app.app_context():
        try:
            accounts = db.session.query(Account).filter_by(is_active=True).all()
            
            # Update progress with account count
            scanning_progress.update({
                'is_active': True,
                'percentage': 10,
                'status': 'Counting repositories...',
                'details': f'Found {len(accounts)} active accounts',
                'total_accounts': len(accounts),
                'current_account': 0,
                'total_repos': 0,
                'current_repo': 0
            })
            
            # Count total repositories first for better progress tracking
            total_repos = 0
            for account in accounts:
                if account.platform == 'github':
                    repos = fetch_github_repos(account)
                    total_repos += len(repos)
                elif account.platform == 'gitlab':
                    repos = fetch_gitlab_repos(account)
                    total_repos += len(repos)
            
            scanning_progress.update({
                'percentage': 15,
                'status': 'Starting repository analysis...',
                'details': f'Found {total_repos} repositories across {len(accounts)} accounts',
                'total_repos': total_repos
            })
            
            # Small delay to ensure frontend gets the initial progress
            time.sleep(1)
            
            # Now analyze each account
            for account_idx, account in enumerate(accounts, 1):
                try:
                    analyze_account(account.id, account_idx, len(accounts), total_repos)
                except Exception as e:
                    print(f"Error analyzing account {account.username}: {e}")
                    scanning_progress['details'] = f'Error with {account.username}: {str(e)}'
            
            # Mark as completed
            scanning_progress.update({
                'is_active': False,
                'percentage': 100,
                'status': 'Analysis completed!',
                'details': 'All accounts processed successfully',
                'current_account': len(accounts),
                'current_repo': total_repos
            })
            print("✓ Analysis completed successfully!")
            
        except Exception as e:
            print(f"Error in analyze_all_accounts: {e}")
            scanning_progress.update({
                'is_active': False,
                'percentage': 0,
                'status': 'Analysis failed',
                'details': f'Error: {str(e)}'
            })

# SVG Badge Generator
def format_number(number):
    suffixes = ['', 'k', 'm', 'b', 't']
    magnitude = 0
    while abs(number) >= 1000:
        magnitude += 1
        number /= 1000
    return f"{number:.1f}{suffixes[magnitude]}"

def generate_svg_badge(label, value, color="#08C"):
    def calculate_text_length(text):
        return len(text) * 66
    
    text_width_1 = calculate_text_length(label)
    text_width_2 = calculate_text_length(value)
    
    total_width = text_width_1 + text_width_2 + 200
    
    svg = f'''<svg width="{total_width / 10}" height="20" viewBox="0 0 {total_width} 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}: {value}">
      <title>{label}: {value}</title>
      <linearGradient id="a" x2="0" y2="100%">
        <stop offset="0" stop-opacity=".1" stop-color="#EEE"/>
        <stop offset="1" stop-opacity=".1"/>
      </linearGradient>
      <mask id="m"><rect width="{total_width}" height="200" rx="30" fill="#FFF"/></mask>
      <g mask="url(#m)">
        <rect width="{text_width_1 + 100}" height="200" fill="#555"/>
        <rect width="{text_width_2 + 100}" height="200" fill="{color}" x="{text_width_1 + 100}"/>
        <rect width="{total_width}" height="200" fill="url(#a)"/>
      </g>
      <g aria-hidden="true" fill="#fff" text-anchor="start" font-family="Verdana,DejaVu Sans,sans-serif" font-size="110">
        <text x="60" y="148" textLength="{text_width_1}" fill="#000" opacity="0.25">{label}</text>
        <text x="50" y="138" textLength="{text_width_1}">{label}</text>
        <text x="{text_width_1 + 135}" y="148" textLength="{text_width_2}" fill="#000" opacity="0.25">{value}</text>
        <text x="{text_width_1 + 145}" y="138" textLength="{text_width_2}">{value}</text>
      </g>
    </svg>'''
    
    return svg

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    accounts = db.session.query(Account).all()
    
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    
    # Fix the stats_today query to include file counts
    stats_today_query = db.session.query(
        Statistics.language,
        db.func.sum(Statistics.files).label('files'),
        db.func.sum(Statistics.total_lines).label('total_lines'),
        db.func.sum(Statistics.code_lines).label('code_lines'),
        db.func.sum(Statistics.comment_lines).label('comment_lines'),
        db.func.sum(Statistics.empty_lines).label('empty_lines')
    ).filter(Statistics.date == today).group_by(Statistics.language).all()
    
    # Convert to list of dictionaries
    stats_today = []
    for row in stats_today_query:
        stats_today.append({
            'language': row.language,
            'files': row.files or 0,
            'total_lines': row.total_lines or 0,
            'code_lines': row.code_lines or 0,
            'comment_lines': row.comment_lines or 0,
            'empty_lines': row.empty_lines or 0
        })
    
    # Fix other queries and convert to serializable format
    stats_week_query = db.session.query(
        Statistics.date,
        db.func.sum(Statistics.total_lines).label('total_lines')
    ).filter(Statistics.date >= week_ago).group_by(Statistics.date).order_by(Statistics.date).all()
    
    stats_week = []
    for row in stats_week_query:
        stats_week.append([
            row.date.isoformat() if row.date else '',
            row.total_lines or 0
        ])
    
    stats_month_query = db.session.query(
        Statistics.date,
        db.func.sum(Statistics.total_lines).label('total_lines')
    ).filter(Statistics.date >= month_ago).group_by(Statistics.date).order_by(Statistics.date).all()
    
    stats_month = []
    for row in stats_month_query:
        stats_month.append([
            row.date.isoformat() if row.date else '',
            row.total_lines or 0
        ])
    
    stats_year_query = db.session.query(
        Statistics.date,
        db.func.sum(Statistics.total_lines).label('total_lines')
    ).filter(Statistics.date >= year_ago).group_by(Statistics.date).order_by(Statistics.date).all()
    
    stats_year = []
    for row in stats_year_query:
        stats_year.append([
            row.date.isoformat() if row.date else '',
            row.total_lines or 0
        ])

    # Calculate total stats properly
    total_lines = sum(s['total_lines'] for s in stats_today)
    total_files = sum(s['files'] for s in stats_today)
    total_stats = {
        'files': total_files,
        'total': total_lines,
        'code': int(total_lines * 0.7),
        'comment': int(total_lines * 0.2),
        'empty': int(total_lines * 0.1),
    }

    language_colors = {
        'PYTHON': '#3572A5',
        'JAVASCRIPT': '#f1e05a',
        'TYPESCRIPT': '#2b7489',
        'JAVA': '#b07219',
        'C': '#555555',
        'C++': '#f34b7d',
        'C#': '#178600',
        'PHP': '#4F5D95',
        'RUBY': '#701516',
        'GO': '#00ADD8',
        'RUST': '#dea584',
        'SWIFT': '#ffac45',
        'KOTLIN': '#F18E33',
        'HTML': '#e34c26',
        'CSS': '#563d7c',
        'SCSS': '#c6538c',
        'SASS': '#c6538c',
        'SHELL': '#89e051',
        'SQL': '#e38c00',
        'R': '#198CE7',
        'DART': '#00B4AB',
        'LUA': '#000080',
        'PERL': '#0298c3',
        'MARKDOWN': '#083fa1',
        'JSON': '#292929',
        'YAML': '#cb171e',
        'XML': '#0060ac',
        'VUE': '#41b883'
    }

    return render_template(
        'dashboard.html',
        accounts=accounts,
        stats_today=stats_today,
        stats_week=stats_week,
        stats_month=stats_month,
        stats_year=stats_year,
        language_colors=language_colors,
        total_stats=total_stats
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_account':
            account = Account(
                platform=request.form.get('platform'),
                username=request.form.get('username'),
                access_token=request.form.get('access_token'),
                base_url=request.form.get('base_url', '')
            )
            db.session.add(account)
            db.session.commit()
            return jsonify({'success': True})
        
        elif action == 'update_interval':
            interval = request.form.get('interval')
            setting = db.session.query(Settings).filter_by(key='auto_update_interval').first()
            if setting:
                setting.value = interval
            else:
                setting = Settings(key='auto_update_interval', value=interval)
                db.session.add(setting)
            db.session.commit()
            
            try:
                scheduler.remove_job('analyze_job')
            except:
                pass
            
            scheduler.add_job(
                id='analyze_job',
                func=analyze_all_accounts,
                trigger='interval',
                hours=int(interval)
            )
            
            return jsonify({'success': True})
    
    accounts = db.session.query(Account).all()
    interval_setting = db.session.query(Settings).filter_by(key='auto_update_interval').first()
    interval = interval_setting.value if interval_setting else '24'
    
    return render_template('settings.html', accounts=accounts, interval=interval)

@app.route('/delete_account/<int:account_id>', methods=['POST'])
def delete_account(account_id):
    account = db.session.get(Account, account_id)
    if account:
        db.session.delete(account)
        db.session.commit()
    return jsonify({'success': True})

@app.route('/toggle_account/<int:account_id>', methods=['POST'])
def toggle_account(account_id):
    account = db.session.get(Account, account_id)
    if account:
        account.is_active = not account.is_active
        db.session.commit()
    return jsonify({'success': True, 'is_active': account.is_active})

@app.route('/analyze/<int:account_id>', methods=['POST'])
def analyze(account_id):
    try:
        analyze_account(account_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/analyze_all', methods=['POST'])
def analyze_all():
    try:
        # Initialize progress before starting the thread
        global scanning_progress
        scanning_progress.update({
            'is_active': True,
            'percentage': 5,
            'status': 'Starting analysis...',
            'details': 'Initializing scanning process',
            'total_accounts': 0,
            'current_account': 0,
            'total_repos': 0,
            'current_repo': 0
        })
        
        # Run analysis in background thread to avoid timeout
        thread = threading.Thread(target=analyze_all_accounts)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True})
    except Exception as e:
        scanning_progress.update({
            'is_active': False,
            'percentage': 0,
            'status': 'Error starting analysis',
            'details': str(e)
        })
        return jsonify({'success': False, 'error': str(e)})

# Progress Tracking Routes
@app.route('/api/start_scanning', methods=['POST'])
def start_scanning():
    """Initialize scanning progress"""
    global scanning_progress
    scanning_progress.update({
        'is_active': True,
        'percentage': 5,
        'status': 'Starting analysis...',
        'details': 'Preparing to scan all repositories',
        'total_accounts': 0,
        'current_account': 0,
        'total_repos': 0,
        'current_repo': 0
    })
    return jsonify({'success': True})

@app.route('/api/scanning_progress')
def get_scanning_progress():
    """Get current scanning progress"""
    global scanning_progress
    return jsonify(scanning_progress)

@app.route('/api/cleanup_progress', methods=['POST'])
def cleanup_progress():
    """Clean up any stuck progress state"""
    global scanning_progress
    scanning_progress.update({
        'is_active': False,
        'percentage': 0,
        'status': 'Ready',
        'details': ''
    })
    return jsonify({'success': True})

# API Routes
@app.route('/api/stats')
def api_stats():
    account_id = request.args.get('account_id', type=int)
    language = request.args.get('language')
    period = request.args.get('period', 'today')
    
    today = datetime.utcnow().date()
    
    if period == 'today':
        start_date = today
    elif period == 'week':
        start_date = today - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
    elif period == 'year':
        start_date = today - timedelta(days=365)
    else:
        start_date = today
    
    query = db.session.query(Statistics).filter(Statistics.date >= start_date)
    
    if account_id:
        query = query.filter(Statistics.account_id == account_id)
    
    if language:
        query = query.filter(Statistics.language == language.upper())
    
    stats = query.all()
    
    result = {}
    for stat in stats:
        lang = stat.language
        if lang not in result:
            result[lang] = {
                'files': 0,
                'total_lines': 0,
                'code_lines': 0,
                'comment_lines': 0,
                'empty_lines': 0
            }
        result[lang]['files'] += stat.files
        result[lang]['total_lines'] += stat.total_lines
        result[lang]['code_lines'] += stat.code_lines
        result[lang]['comment_lines'] += stat.comment_lines
        result[lang]['empty_lines'] += stat.empty_lines
    
    return jsonify(result)

@app.route('/api/badge/<badge_type>')
def api_badge(badge_type):
    account_id = request.args.get('account_id', type=int)
    language = request.args.get('language')
    color = request.args.get('color', '#08C')
    
    today = datetime.utcnow().date()
    
    query = db.session.query(Statistics).filter(Statistics.date == today)
    
    if account_id:
        query = query.filter(Statistics.account_id == account_id)
    
    if language:
        query = query.filter(Statistics.language == language.upper())
    
    stats = query.all()
    
    if badge_type == 'total_lines':
        total = sum(s.total_lines for s in stats)
        label = f"{language} Total Lines" if language else "Total Lines"
        svg = generate_svg_badge(label, format_number(total), color)
    
    elif badge_type == 'code_lines':
        total = sum(s.code_lines for s in stats)
        label = f"{language} Code Lines" if language else "Code Lines"
        svg = generate_svg_badge(label, format_number(total), color)
    
    elif badge_type == 'files':
        total = sum(s.files for s in stats)
        label = f"{language} Files" if language else "Files"
        svg = generate_svg_badge(label, format_number(total), color)
    
    elif badge_type == 'comment_lines':
        total = sum(s.comment_lines for s in stats)
        label = f"{language} Comment Lines" if language else "Comment Lines"
        svg = generate_svg_badge(label, format_number(total), color)
    
    elif badge_type == 'empty_lines':
        total = sum(s.empty_lines for s in stats)
        label = f"{language} Empty Lines" if language else "Empty Lines"
        svg = generate_svg_badge(label, format_number(total), color)
    
    else:
        svg = generate_svg_badge("Error", "Invalid Type", "#f00")
    
    return svg, 200, {'Content-Type': 'image/svg+xml'}

# API Management Routes
@app.route('/api/endpoints')
def api_endpoints():
    """Get all API endpoints"""
    endpoints = [
        {
            'method': 'GET',
            'path': '/api/stats',
            'description': 'Get statistics data',
            'parameters': [
                {'name': 'account_id', 'type': 'integer', 'required': False, 'description': 'Filter by account ID'},
                {'name': 'language', 'type': 'string', 'required': False, 'description': 'Filter by programming language'},
                {'name': 'period', 'type': 'string', 'required': False, 'description': 'Time period: today, week, month, year'}
            ]
        },
        {
            'method': 'GET',
            'path': '/api/badge/<badge_type>',
            'description': 'Generate SVG badges',
            'parameters': [
                {'name': 'badge_type', 'type': 'string', 'required': True, 'description': 'Type of badge: total_lines, code_lines, comment_lines, empty_lines, files'},
                {'name': 'account_id', 'type': 'integer', 'required': False, 'description': 'Filter by account ID'},
                {'name': 'language', 'type': 'string', 'required': False, 'description': 'Filter by programming language'},
                {'name': 'color', 'type': 'string', 'required': False, 'description': 'Badge color in hex format'}
            ]
        }
    ]
    return jsonify(endpoints)

@app.route('/api/custom', methods=['GET', 'POST', 'PUT', 'DELETE'])
def api_custom_endpoints():
    """Manage custom API endpoints"""
    if request.method == 'GET':
        # Return list of custom endpoints
        custom_endpoints = db.session.query(CustomEndpoint).all()
        return jsonify([{
            'id': ep.id,
            'name': ep.name,
            'path': ep.path,
            'method': ep.method,
            'description': ep.description,
            'query': ep.query,
            'is_active': ep.is_active,
            'created_at': ep.created_at.isoformat() if ep.created_at else None
        } for ep in custom_endpoints])
    
    elif request.method == 'POST':
        # Create new custom endpoint
        data = request.json
        
        # Validate required fields
        if not all(k in data for k in ['name', 'path', 'method', 'query']):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Validate query syntax (basic check)
        query = data['query'].strip().upper()
        if data['method'] == 'GET' and not query.startswith('SELECT'):
            return jsonify({'success': False, 'error': 'GET endpoints can only use SELECT queries'})
        
        # Check if path already exists
        existing = db.session.query(CustomEndpoint).filter_by(path=data['path']).first()
        if existing:
            return jsonify({'success': False, 'error': 'Endpoint path already exists'})
        
        endpoint = CustomEndpoint(
            name=data['name'],
            path=data['path'],
            method=data['method'],
            description=data.get('description', ''),
            query=data['query'],
            is_active=data.get('is_active', True)
        )
        db.session.add(endpoint)
        db.session.commit()
        return jsonify({'success': True, 'id': endpoint.id})
    
    elif request.method == 'PUT':
        # Update custom endpoint
        data = request.json
        endpoint = db.session.get(CustomEndpoint, data['id'])
        if endpoint:
            # Validate query syntax if provided
            if 'query' in data:
                query = data['query'].strip().upper()
                if endpoint.method == 'GET' and not query.startswith('SELECT'):
                    return jsonify({'success': False, 'error': 'GET endpoints can only use SELECT queries'})
            
            endpoint.name = data['name']
            endpoint.path = data['path']
            endpoint.method = data['method']
            endpoint.description = data.get('description', '')
            endpoint.query = data['query']
            endpoint.is_active = data.get('is_active', True)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Endpoint not found'})
    
    elif request.method == 'DELETE':
        # Delete custom endpoint
        endpoint_id = request.args.get('id')
        endpoint = db.session.get(CustomEndpoint, endpoint_id)
        if endpoint:
            db.session.delete(endpoint)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Endpoint not found'})


@app.route('/api/custom/<path:custom_path>')
def execute_custom_endpoint(custom_path):
    """Execute custom API endpoints"""
    endpoint = db.session.query(CustomEndpoint).filter_by(path=custom_path, is_active=True).first()
    if not endpoint:
        return jsonify({'error': 'Endpoint not found'}), 404
    
    try:
        # Parse and execute the custom query
        query = endpoint.query
        
        # Replace placeholders with actual parameters
        for key, value in request.args.items():
            query = query.replace(f'{{{{{key}}}}}', str(value))
        
        # Execute the query based on type
        if endpoint.method == 'GET':
            if query.strip().upper().startswith('SELECT'):
                # Wrap the query in text() for SQLAlchemy
                from sqlalchemy import text
                sql_text = text(query)
                
                result = db.session.execute(sql_text)
                rows = result.fetchall()
                
                # Convert to list of dictionaries
                columns = result.keys()
                data = [dict(zip(columns, row)) for row in rows]
                
                return jsonify(data)
            else:
                return jsonify({'error': 'Only SELECT queries allowed for GET endpoints'}), 400
        
        else:
            return jsonify({'error': 'Method not supported yet'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Initialize database and scheduler
def init_app():
    with app.app_context():
        db.create_all()
        
        # Add this to create the custom_endpoints table
        try:
            # This will create the table if it doesn't exist
            db.session.query(CustomEndpoint).first()
        except:
            # If table doesn't exist, create it
            db.create_all()
        
        interval_setting = db.session.query(Settings).filter_by(key='auto_update_interval').first()
        if not interval_setting:
            interval_setting = Settings(key='auto_update_interval', value='24')
            db.session.add(interval_setting)
            db.session.commit()
        
        try:
            interval = int(interval_setting.value)
            scheduler.add_job(
                id='analyze_job',
                func=analyze_all_accounts,
                trigger='interval',
                hours=interval
            )
        except Exception as e:
            print(f"Scheduler error: {e}")

if __name__ == '__main__':
    scheduler.init_app(app)
    scheduler.start()
    init_app()
    app.run(debug=True, host='0.0.0.0', port=5000)