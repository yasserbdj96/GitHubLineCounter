#!/usr/bin/env python
# coding:utf-8

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
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
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-to-something-secure'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///code_stats.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = APScheduler()
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100))
    bio = db.Column(db.Text)
    avatar_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    timezone = db.Column(db.String(50), default='UTC')
    theme = db.Column(db.String(20), default='light')
    
    accounts = db.relationship('Account', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    platform = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(100), nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    base_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime)
    
    repositories = db.relationship('Repository', backref='account', lazy=True, cascade='all, delete-orphan')

class Repository(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    repo_name = db.Column(db.String(200), nullable=False)
    repo_id = db.Column(db.String(100), nullable=False)
    repo_hash = db.Column(db.String(64))  # Repository commit hash for change detection
    is_private = db.Column(db.Boolean, default=False)
    last_updated = db.Column(db.DateTime)
    last_commit_date = db.Column(db.DateTime)
    
    files = db.relationship('FileCache', backref='repository', lazy=True, cascade='all, delete-orphan')
    
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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'))
    date = db.Column(db.Date, nullable=False)
    language = db.Column(db.String(50), nullable=False)
    files = db.Column(db.Integer, default=0)
    total_lines = db.Column(db.Integer, default=0)
    code_lines = db.Column(db.Integer, default=0)
    comment_lines = db.Column(db.Integer, default=0)
    empty_lines = db.Column(db.Integer, default=0)
    
    user = db.relationship('User', backref='statistics')

class DailyActivity(db.Model):
    """Store daily coding activity for charts"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    total_lines = db.Column(db.Integer, default=0)
    code_lines = db.Column(db.Integer, default=0)
    files_modified = db.Column(db.Integer, default=0)
    languages_used = db.Column(db.Integer, default=0)
    
    user = db.relationship('User', backref='daily_activities')

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.String(200))

class CustomEndpoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    path = db.Column(db.String(200), nullable=False)
    method = db.Column(db.String(10), nullable=False, default='GET')
    description = db.Column(db.Text)
    query = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='custom_endpoints')

# Load language definitions
with open('languages.json', 'r') as f:
    LANGUAGES = json.load(f)

# Global variable to track scanning progress per user
scanning_progress = {}

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

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
    
    try:
        return content.decode('utf-8', errors='ignore')
    except:
        return ""

def get_repo_hash(repo, platform='github'):
    """Get repository hash to detect changes"""
    try:
        if platform == 'github':
            # Get latest commit SHA
            commits = repo.get_commits()
            if commits.totalCount > 0:
                return commits[0].sha
        elif platform == 'gitlab':
            # Get latest commit SHA
            commits = repo.commits.list(per_page=1)
            if commits:
                return commits[0].id
    except:
        pass
    return None

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
                'default_branch': repo.default_branch or 'main',
                'repo_obj': repo
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
                'default_branch': project.default_branch or 'main',
                'repo_obj': project
            })
        
        return repos_data
    except Exception as e:
        print(f"Error fetching GitLab repos: {e}")
        return []

def analyze_github_repo(account, repo_info, force=False):
    """Analyze GitHub repository with smart caching"""
    g = Github(account.access_token)
    repo = repo_info.get('repo_obj') or g.get_repo(f"{account.username}/{repo_info['name']}")
    
    db_repo = db.session.query(Repository).filter_by(
        account_id=account.id,
        repo_id=repo_info['id']
    ).first()
    
    # Check if repository has changed
    current_hash = get_repo_hash(repo, 'github')
    
    if not db_repo:
        db_repo = Repository(
            account_id=account.id,
            repo_name=repo_info['name'],
            repo_id=repo_info['id'],
            is_private=repo_info['private'],
            repo_hash=current_hash
        )
        db.session.add(db_repo)
        db.session.commit()
    elif not force and db_repo.repo_hash == current_hash:
        # Repository hasn't changed, use cached data
        print(f"  ⚡ Using cached data for {repo_info['name']} (no changes)")
        stats = {}
        for cached_file in db_repo.files:
            lang_name = cached_file.language
            if lang_name not in stats:
                stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
            stats[lang_name]['files'] += 1
            stats[lang_name]['total'] += cached_file.total_lines
            stats[lang_name]['code'] += cached_file.code_lines
            stats[lang_name]['comment'] += cached_file.comment_lines
            stats[lang_name]['empty'] += cached_file.empty_lines
        return stats
    
    # Repository has changed, update it
    print(f"  🔄 Repository changed, updating {repo_info['name']}")
    db_repo.repo_hash = current_hash
    
    stats = {}
    
    try:
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
        
        if file_obj.size > 10 * 1024 * 1024:
            print(f"Skipping large file (>{file_obj.size} bytes): {file_content.path}")
            return
        
        content = None
        
        try:
            if hasattr(file_obj, 'decoded_content') and file_obj.decoded_content:
                content = decode_content(file_obj.decoded_content)
            elif file_obj.encoding == 'none' or not content:
                raw_url = file_obj.download_url
                if raw_url:
                    response = requests.get(raw_url, timeout=30)
                    if response.status_code == 200:
                        content = decode_content(response.content)
            elif file_obj.content:
                raw_content = base64.b64decode(file_obj.content)
                content = decode_content(raw_content)
                
        except Exception as e:
            print(f"Could not decode {file_content.path}: {e}")
            return
        
        if not content or is_binary_content(content):
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

def analyze_gitlab_repo(account, repo_info, force=False):
    """Analyze GitLab repository with smart caching"""
    try:
        if account.base_url:
            gl = gitlab.Gitlab(account.base_url, private_token=account.access_token)
        else:
            gl = gitlab.Gitlab('https://gitlab.com', private_token=account.access_token)
        
        gl.auth()
        project = repo_info.get('repo_obj') or gl.projects.get(repo_info['id'])
        
        db_repo = db.session.query(Repository).filter_by(
            account_id=account.id,
            repo_id=repo_info['id']
        ).first()
        
        # Check if repository has changed
        current_hash = get_repo_hash(project, 'gitlab')
        
        if not db_repo:
            db_repo = Repository(
                account_id=account.id,
                repo_name=repo_info['name'],
                repo_id=repo_info['id'],
                is_private=repo_info['private'],
                repo_hash=current_hash
            )
            db.session.add(db_repo)
            db.session.commit()
        elif not force and db_repo.repo_hash == current_hash:
            # Repository hasn't changed, use cached data
            print(f"  ⚡ Using cached data for {repo_info['name']} (no changes)")
            stats = {}
            for cached_file in db_repo.files:
                lang_name = cached_file.language
                if lang_name not in stats:
                    stats[lang_name] = {'files': 0, 'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
                stats[lang_name]['files'] += 1
                stats[lang_name]['total'] += cached_file.total_lines
                stats[lang_name]['code'] += cached_file.code_lines
                stats[lang_name]['comment'] += cached_file.comment_lines
                stats[lang_name]['empty'] += cached_file.empty_lines
            return stats
        
        # Repository has changed, update it
        print(f"  🔄 Repository changed, updating {repo_info['name']}")
        db_repo.repo_hash = current_hash
        
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

def save_statistics(user_id, account_id, stats, target_date=None):
    """Save statistics for a specific date"""
    if not target_date:
        target_date = datetime.utcnow().date()
    
    # Delete old statistics for this date
    db.session.query(Statistics).filter_by(
        user_id=user_id,
        account_id=account_id,
        date=target_date
    ).delete()
    
    total_lines = 0
    total_files = 0
    languages_count = len(stats)
    
    for language, data in stats.items():
        stat = Statistics(
            user_id=user_id,
            account_id=account_id,
            date=target_date,
            language=language,
            files=data['files'],
            total_lines=data['total'],
            code_lines=data['code'],
            comment_lines=data['comment'],
            empty_lines=data['empty']
        )
        db.session.add(stat)
        total_lines += data['total']
        total_files += data['files']
    
    # Update daily activity
    daily = db.session.query(DailyActivity).filter_by(
        user_id=user_id,
        date=target_date
    ).first()
    
    if daily:
        daily.total_lines = total_lines
        daily.code_lines = int(total_lines * 0.7)
        daily.files_modified = total_files
        daily.languages_used = languages_count
    else:
        daily = DailyActivity(
            user_id=user_id,
            date=target_date,
            total_lines=total_lines,
            code_lines=int(total_lines * 0.7),
            files_modified=total_files,
            languages_used=languages_count
        )
        db.session.add(daily)
    
    db.session.commit()

def analyze_account(account_id, user_id, force=False):
    """Analyze single account with smart caching"""
    global scanning_progress
    
    account = db.session.get(Account, account_id)
    if not account or not account.is_active:
        return
    
    print(f"\n{'='*60}")
    print(f"Analyzing account: {account.username} ({account.platform})")
    print(f"{'='*60}")
    
    all_stats = {}
    
    if account.platform == 'github':
        repos = fetch_github_repos(account)
        print(f"Found {len(repos)} repositories")
        
        for repo_idx, repo in enumerate(repos, 1):
            print(f"\n[{repo_idx}/{len(repos)}] Analyzing repo: {repo['name']}...")
            repo_stats = analyze_github_repo(account, repo, force=force)
            
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
            print(f"\n[{repo_idx}/{len(repos)}] Analyzing repo: {repo['name']}...")
            repo_stats = analyze_gitlab_repo(account, repo, force=force)
            
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
    
    save_statistics(user_id, account.id, all_stats)
    account.last_sync = datetime.utcnow()
    db.session.commit()
    
    print(f"\n{'='*60}")
    print(f"✓ Completed analysis for {account.username}")
    print(f"{'='*60}\n")

def analyze_user_accounts(user_id, force=False):
    """Analyze all accounts for a user"""
    global scanning_progress
    
    with app.app_context():
        try:
            accounts = db.session.query(Account).filter_by(
                user_id=user_id,
                is_active=True
            ).all()
            
            scanning_progress[user_id] = {
                'is_active': True,
                'percentage': 10,
                'status': 'Starting analysis...',
                'details': f'Found {len(accounts)} active accounts',
                'total_accounts': len(accounts),
                'current_account': 0
            }
            
            for account_idx, account in enumerate(accounts, 1):
                try:
                    scanning_progress[user_id].update({
                        'current_account': account_idx,
                        'percentage': 10 + (account_idx / len(accounts)) * 80,
                        'status': f'Analyzing {account.username}...',
                        'details': f'Account {account_idx} of {len(accounts)}'
                    })
                    
                    analyze_account(account.id, user_id, force=force)
                except Exception as e:
                    print(f"Error analyzing account {account.username}: {e}")
            
            scanning_progress[user_id].update({
                'is_active': False,
                'percentage': 100,
                'status': 'Analysis completed!',
                'details': 'All accounts processed successfully'
            })
            
        except Exception as e:
            print(f"Error in analyze_user_accounts: {e}")
            scanning_progress[user_id] = {
                'is_active': False,
                'percentage': 0,
                'status': 'Analysis failed',
                'details': str(e)
            }

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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = db.session.query(User).filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name', '')
        
        # Check if user exists
        if db.session.query(User).filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if db.session.query(User).filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Create new user
        user = User(username=username, email=email, full_name=full_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get date range from query params
    period = request.args.get('period', 'today')
    
    today = datetime.utcnow().date()
    
    if period == 'today':
        start_date = today
        end_date = today
    elif period == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif period == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif period == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:
        start_date = today
        end_date = today
    
    # Get user accounts
    accounts = db.session.query(Account).filter_by(user_id=current_user.id).all()
    
    # Get statistics for the period
    stats_query = db.session.query(
        Statistics.language,
        db.func.sum(Statistics.files).label('files'),
        db.func.sum(Statistics.total_lines).label('total_lines'),
        db.func.sum(Statistics.code_lines).label('code_lines'),
        db.func.sum(Statistics.comment_lines).label('comment_lines'),
        db.func.sum(Statistics.empty_lines).label('empty_lines')
    ).filter(
        Statistics.user_id == current_user.id,
        Statistics.date >= start_date,
        Statistics.date <= end_date
    ).group_by(Statistics.language).all()
    
    stats_data = []
    for row in stats_query:
        stats_data.append({
            'language': row.language,
            'files': row.files or 0,
            'total_lines': row.total_lines or 0,
            'code_lines': row.code_lines or 0,
            'comment_lines': row.comment_lines or 0,
            'empty_lines': row.empty_lines or 0
        })
    
    # Get daily activity for charts
    activity_query = db.session.query(DailyActivity).filter(
        DailyActivity.user_id == current_user.id,
        DailyActivity.date >= start_date,
        DailyActivity.date <= end_date
    ).order_by(DailyActivity.date).all()
    
    activity_data = []
    for activity in activity_query:
        activity_data.append({
            'date': activity.date.isoformat(),
            'total_lines': activity.total_lines,
            'code_lines': activity.code_lines,
            'files': activity.files_modified,
            'languages': activity.languages_used
        })
    
    # Calculate totals
    total_lines = sum(s['total_lines'] for s in stats_data)
    total_files = sum(s['files'] for s in stats_data)
    total_code_lines = sum(s['code_lines'] for s in stats_data)
    total_comment_lines = sum(s['comment_lines'] for s in stats_data)
    total_empty_lines = sum(s['empty_lines'] for s in stats_data)
    
    total_stats = {
        'files': total_files,
        'total': total_lines,
        'code': total_code_lines,
        'comment': total_comment_lines,
        'empty': total_empty_lines,
    }
    
    # Language colors
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
        'dashboard_new.html',
        accounts=accounts,
        stats_data=stats_data,
        activity_data=activity_data,
        language_colors=language_colors,
        total_stats=total_stats,
        period=period,
        user=current_user
    )

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name', '')
        current_user.bio = request.form.get('bio', '')
        current_user.email = request.form.get('email', current_user.email)
        current_user.timezone = request.form.get('timezone', 'UTC')
        current_user.theme = request.form.get('theme', 'light')
        
        # Update password if provided
        new_password = request.form.get('new_password')
        if new_password:
            current_password = request.form.get('current_password')
            if current_user.check_password(current_password):
                current_user.set_password(new_password)
                flash('Password updated successfully!', 'success')
            else:
                flash('Current password is incorrect', 'error')
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html', user=current_user)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_account':
            account = Account(
                user_id=current_user.id,
                platform=request.form.get('platform'),
                username=request.form.get('username'),
                access_token=request.form.get('access_token'),
                base_url=request.form.get('base_url', '')
            )
            db.session.add(account)
            db.session.commit()
            flash('Account added successfully!', 'success')
            return redirect(url_for('settings'))
        
        elif action == 'update_interval':
            interval = request.form.get('interval')
            setting = db.session.query(Settings).filter_by(
                user_id=current_user.id,
                key='auto_update_interval'
            ).first()
            
            if setting:
                setting.value = interval
            else:
                setting = Settings(
                    user_id=current_user.id,
                    key='auto_update_interval',
                    value=interval
                )
                db.session.add(setting)
            db.session.commit()
            flash('Update interval saved!', 'success')
            return redirect(url_for('settings'))
    
    accounts = db.session.query(Account).filter_by(user_id=current_user.id).all()
    interval_setting = db.session.query(Settings).filter_by(
        user_id=current_user.id,
        key='auto_update_interval'
    ).first()
    interval = interval_setting.value if interval_setting else '24'
    
    return render_template('settings_new.html', accounts=accounts, interval=interval, user=current_user)

@app.route('/delete_account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    account = db.session.get(Account, account_id)
    if account and account.user_id == current_user.id:
        db.session.delete(account)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Account not found'})

@app.route('/toggle_account/<int:account_id>', methods=['POST'])
@login_required
def toggle_account(account_id):
    account = db.session.get(Account, account_id)
    if account and account.user_id == current_user.id:
        account.is_active = not account.is_active
        db.session.commit()
        return jsonify({'success': True, 'is_active': account.is_active})
    return jsonify({'success': False, 'error': 'Account not found'})

@app.route('/analyze_all', methods=['POST'])
@login_required
def analyze_all():
    try:
        force = request.json.get('force', False) if request.is_json else False
        
        global scanning_progress
        scanning_progress[current_user.id] = {
            'is_active': True,
            'percentage': 5,
            'status': 'Starting analysis...',
            'details': 'Initializing scanning process'
        }
        
        # Run analysis in background thread
        thread = threading.Thread(
            target=analyze_user_accounts,
            args=(current_user.id, force)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/scanning_progress')
@login_required
def get_scanning_progress():
    """Get current scanning progress for user"""
    global scanning_progress
    progress = scanning_progress.get(current_user.id, {
        'is_active': False,
        'percentage': 0,
        'status': 'Ready',
        'details': ''
    })
    return jsonify(progress)

# API Routes
@app.route('/api/stats')
@login_required
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
    
    query = db.session.query(Statistics).filter(
        Statistics.user_id == current_user.id,
        Statistics.date >= start_date
    )
    
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
    # Public badges - check for user parameter
    username = request.args.get('user')
    if not username:
        if not current_user.is_authenticated:
            return generate_svg_badge("Error", "Authentication Required", "#f00"), 200, {'Content-Type': 'image/svg+xml'}
        user_id = current_user.id
    else:
        user = db.session.query(User).filter_by(username=username).first()
        if not user:
            return generate_svg_badge("Error", "User Not Found", "#f00"), 200, {'Content-Type': 'image/svg+xml'}
        user_id = user.id
    
    language = request.args.get('language')
    color = request.args.get('color', '#08C')
    
    today = datetime.utcnow().date()
    
    query = db.session.query(Statistics).filter(
        Statistics.user_id == user_id,
        Statistics.date == today
    )
    
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

@app.route('/api/custom', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_custom_endpoints():
    """Manage custom API endpoints"""
    if request.method == 'GET':
        custom_endpoints = db.session.query(CustomEndpoint).filter_by(
            user_id=current_user.id
        ).all()
        return jsonify([{
            'id': ep.id,
            'name': ep.name,
            'path': ep.path,
            'method': ep.method,
            'description': ep.description,
            'query': ep.query,
            'is_active': ep.is_active,
            'is_public': ep.is_public,
            'created_at': ep.created_at.isoformat() if ep.created_at else None
        } for ep in custom_endpoints])
    
    elif request.method == 'POST':
        data = request.json
        
        if not all(k in data for k in ['name', 'path', 'method', 'query']):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        query = data['query'].strip().upper()
        if data['method'] == 'GET' and not query.startswith('SELECT'):
            return jsonify({'success': False, 'error': 'GET endpoints can only use SELECT queries'})
        
        existing = db.session.query(CustomEndpoint).filter_by(
            user_id=current_user.id,
            path=data['path']
        ).first()
        if existing:
            return jsonify({'success': False, 'error': 'Endpoint path already exists'})
        
        endpoint = CustomEndpoint(
            user_id=current_user.id,
            name=data['name'],
            path=data['path'],
            method=data['method'],
            description=data.get('description', ''),
            query=data['query'],
            is_active=data.get('is_active', True),
            is_public=data.get('is_public', False)
        )
        db.session.add(endpoint)
        db.session.commit()
        return jsonify({'success': True, 'id': endpoint.id})
    
    elif request.method == 'PUT':
        data = request.json
        endpoint = db.session.get(CustomEndpoint, data['id'])
        if endpoint and endpoint.user_id == current_user.id:
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
            endpoint.is_public = data.get('is_public', False)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Endpoint not found'})
    
    elif request.method == 'DELETE':
        endpoint_id = request.args.get('id')
        endpoint = db.session.get(CustomEndpoint, endpoint_id)
        if endpoint and endpoint.user_id == current_user.id:
            db.session.delete(endpoint)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Endpoint not found'})

@app.route('/api/custom/<username>/<path:custom_path>')
def execute_custom_endpoint(username, custom_path):
    """Execute custom API endpoints"""
    user = db.session.query(User).filter_by(username=username).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    endpoint = db.session.query(CustomEndpoint).filter_by(
        user_id=user.id,
        path=custom_path,
        is_active=True
    ).first()
    
    if not endpoint:
        return jsonify({'error': 'Endpoint not found'}), 404
    
    # Check if endpoint is public or user is authenticated
    if not endpoint.is_public and (not current_user.is_authenticated or current_user.id != user.id):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        query = endpoint.query
        
        # Replace placeholders
        for key, value in request.args.items():
            query = query.replace(f'{{{{{key}}}}}', str(value))
        
        if endpoint.method == 'GET':
            if query.strip().upper().startswith('SELECT'):
                from sqlalchemy import text
                sql_text = text(query)
                
                result = db.session.execute(sql_text)
                rows = result.fetchall()
                
                columns = result.keys()
                data = [dict(zip(columns, row)) for row in rows]
                
                return jsonify(data)
            else:
                return jsonify({'error': 'Only SELECT queries allowed for GET endpoints'}), 400
        else:
            return jsonify({'error': 'Method not supported yet'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/<username>')
def public_profile(username):
    """Public profile page similar to WakaTime"""
    user = db.session.query(User).filter_by(username=username).first()
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('index'))
    
    # Get statistics for the last 30 days
    start_date = datetime.utcnow().date() - timedelta(days=30)
    
    stats_query = db.session.query(
        Statistics.language,
        db.func.sum(Statistics.files).label('files'),
        db.func.sum(Statistics.total_lines).label('total_lines'),
        db.func.sum(Statistics.code_lines).label('code_lines'),
        db.func.sum(Statistics.comment_lines).label('comment_lines'),
        db.func.sum(Statistics.empty_lines).label('empty_lines')
    ).filter(
        Statistics.user_id == user.id,
        Statistics.date >= start_date
    ).group_by(Statistics.language).all()
    
    stats_data = []
    for row in stats_query:
        stats_data.append({
            'language': row.language,
            'files': row.files or 0,
            'total_lines': row.total_lines or 0,
            'code_lines': row.code_lines or 0,
            'comment_lines': row.comment_lines or 0,
            'empty_lines': row.empty_lines or 0
        })
    
    # Get daily activity for charts
    activity_query = db.session.query(DailyActivity).filter(
        DailyActivity.user_id == user.id,
        DailyActivity.date >= start_date
    ).order_by(DailyActivity.date).all()
    
    activity_data = []
    for activity in activity_query:
        activity_data.append({
            'date': activity.date.isoformat(),
            'total_lines': activity.total_lines,
            'code_lines': activity.code_lines,
            'files': activity.files_modified,
            'languages': activity.languages_used
        })
    
    # Calculate totals
    total_lines = sum(s['total_lines'] for s in stats_data)
    total_files = sum(s['files'] for s in stats_data)
    total_code_lines = sum(s['code_lines'] for s in stats_data)
    
    total_stats = {
        'files': total_files,
        'total': total_lines,
        'code': total_code_lines,
    }
    
    # Language colors (same as dashboard)
    language_colors = {
        'PYTHON': '#3572A5', 'JAVASCRIPT': '#f1e05a', 'TYPESCRIPT': '#2b7489',
        'JAVA': '#b07219', 'C': '#555555', 'C++': '#f34b7d', 'C#': '#178600',
        'PHP': '#4F5D95', 'RUBY': '#701516', 'GO': '#00ADD8', 'RUST': '#dea584',
        'SWIFT': '#ffac45', 'KOTLIN': '#F18E33', 'HTML': '#e34c26', 'CSS': '#563d7c',
        'SCSS': '#c6538c', 'SHELL': '#89e051', 'SQL': '#e38c00', 'R': '#198CE7',
        'DART': '#00B4AB', 'LUA': '#000080', 'PERL': '#0298c3', 'MARKDOWN': '#083fa1',
        'JSON': '#292929', 'YAML': '#cb171e', 'XML': '#0060ac', 'VUE': '#41b883'
    }
    
    return render_template(
        'public_profile.html',
        profile_user=user,
        stats_data=stats_data,
        activity_data=activity_data,
        language_colors=language_colors,
        total_stats=total_stats
    )

# Initialize database
def init_app():
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    init_app()
    app.run(debug=True, host='0.0.0.0', port=8080)