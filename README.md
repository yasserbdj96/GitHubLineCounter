<!-- Project Header -->
<div align="center">
  <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/logo.png" alt="GitHubLineCounter by yasserbdj96" height="300">
</div>

# Code Statistics Tracker - Flask Web Application

A powerful web application to track and analyze your code statistics across multiple platforms (GitHub, GitLab, and more) with intelligent caching, automated analysis, and beautiful visualizations.

## 🚀 Features

- **Multi-Platform Support**: Connect GitHub, GitLab, and self-hosted instances
- **Smart Caching**: Intelligent file caching system that only reanalyzes changed files
- **Auto-Update**: Configurable automatic analysis at regular intervals
- **Real-time Dashboard**: Beautiful charts showing code statistics over time (day, week, month, year)
- **REST API**: Easy-to-use API for retrieving statistics and generating badges
- **SVG Badges**: Dynamic badge generation for README files
- **Multiple Accounts**: Support for multiple accounts across different platforms
- **No Repository Cloning**: Analyzes code directly via APIs without cloning repos

## 📋 Requirements

- Python 3.8+
- SQLite (included with Python)
- Access tokens for GitHub/GitLab

## 🔧 Installation

1. **Clone the repository**:
```bash
git clone <your-repo-url>
cd code-statistics-tracker
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Create templates directory**:
```bash
mkdir -p templates
```

4. **Add the HTML templates** (base.html, index.html, dashboard.html, settings.html) to the `templates` folder

5. **Make sure languages.json is in the root directory**

6. **Run the application**:
```bash
python app.py
```

7. **Access the application**:
Open your browser and navigate to `http://localhost:5000`

## 🎯 Getting Started

### 1. Add Your Accounts

1. Go to **Settings** page
2. Select platform (GitHub/GitLab)
3. Enter your username
4. Add your access token:
   - **GitHub**: [Generate Personal Access Token](https://github.com/settings/tokens) with `repo` scope
   - **GitLab**: [Generate Personal Access Token](https://gitlab.com/-/profile/personal_access_tokens) with `read_api` scope
5. For self-hosted GitLab, add the base URL
6. Click "Add Account"

### 2. Configure Auto-Update

1. Go to **Settings** page
2. Set update interval (in hours)
3. Click "Save Interval"
4. The system will automatically analyze all active accounts at the specified interval

### 3. Run Analysis

- Click "Analyze All Accounts" on the Dashboard
- Or click "Analyze" for individual accounts in Settings
- First analysis may take time depending on repository size
- Subsequent analyses will be faster due to smart caching

### 4. View Statistics

- Navigate to **Dashboard** to see:
  - Summary cards with key metrics
  - Line charts for week/month/year trends
  - Language breakdown table
  - Real-time badge previews

## 📊 API Usage

### Get Statistics

```bash
GET /api/stats?account_id=1&language=python&period=week
```

**Parameters**:
- `account_id` (optional): Filter by specific account
- `language` (optional): Filter by programming language
- `period` (optional): `today`, `week`, `month`, `year` (default: `today`)

**Response**:
```json
{
  "PYTHON": {
    "files": 150,
    "total_lines": 25000,
    "code_lines": 18000,
    "comment_lines": 5000,
    "empty_lines": 2000
  },
  "JAVASCRIPT": {
    "files": 80,
    "total_lines": 15000,
    "code_lines": 11000,
    "comment_lines": 2500,
    "empty_lines": 1500
  }
}
```

### Generate Badge

```bash
GET /api/badge/{badge_type}?language=python&color=%2308C
```

**Badge Types**:
- `total_lines`: Total lines of code
- `code_lines`: Lines of actual code
- `comment_lines`: Lines of comments
- `empty_lines`: Empty lines
- `files`: Number of files

**Parameters**:
- `account_id` (optional): Filter by account
- `language` (optional): Filter by language
- `color` (optional): Hex color code (URL encoded, e.g., `%2308C` for `#08C`)

**Example Usage in Markdown**:
```markdown
![Python Lines](http://localhost:5000/api/badge/total_lines?language=python)
![Total Files](http://localhost:5000/api/badge/files)
![Code Lines](http://localhost:5000/api/badge/code_lines?color=%23ff6b6b)
```

## 🗄️ Database Schema

### Tables

1. **Account**: Stores platform credentials
2. **Repository**: Tracks repositories per account
3. **FileCache**: Caches file analysis results
4. **Statistics**: Daily statistics per language
5. **Settings**: Application settings

### Smart Caching

The application uses intelligent caching:
- Each file's content hash is stored
- Only changed files are reanalyzed
- Dramatically speeds up subsequent analyses
- Automatically handles file additions/deletions

## 🎨 Supported Languages

The system supports 60+ programming languages including:

- Python, JavaScript, TypeScript
- Java, C, C++, C#
- Go, Rust, Swift, Kotlin
- PHP, Ruby, Perl
- HTML, CSS, Sass
- SQL, Markdown, YAML
- And many more...

See `languages.json` for the complete list.

## ⚙️ Configuration

### Auto-Update Interval

Configure in Settings page (1-168 hours). The scheduler will automatically:
1. Fetch all active accounts
2. Analyze repositories
3. Update statistics
4. Cache results

### Adding Custom Languages

Edit `languages.json`:
```json
{
  "language_key": {
    "name": "LanguageName",
    "extensions": [".ext1", ".ext2"],
    "comment_regex": "regex_pattern"
  }
}
```

## 🔒 Security Notes

- Access tokens are stored in the database (consider encrypting in production)
- Change the `SECRET_KEY` in app.py before deployment
- Use HTTPS in production
- Consider adding user authentication for multi-user environments

## 🚀 Production Deployment

### Using Gunicorn

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Using Docker

```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

### Environment Variables

For production, use environment variables:
```python
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///code_stats.db')
```

## 📈 Performance Optimization

1. **First Analysis**: May take 5-30 minutes depending on repository size
2. **Subsequent Analyses**: 10-100x faster due to caching
3. **Database Indexing**: Automatically handled by SQLAlchemy
4. **Rate Limiting**: Built into GitHub/GitLab APIs (respected automatically)

## 🐛 Troubleshooting

### "Rate limit exceeded"
- GitHub: 5000 requests/hour with token
- GitLab: 10 requests/second
- Solution: Increase auto-update interval

### "Database locked"
- Multiple simultaneous analyses
- Solution: Wait for current analysis to complete

### "Invalid token"
- Token expired or wrong permissions
- Solution: Generate new token with correct scopes

> ## Screenshots:

<p align="center">
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/home.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/home.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-1.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-1.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-2.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-2.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-3.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/settings-3.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-0.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-0.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-1.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-1.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-2.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-2.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-3.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-3.png" alt="Preview" width="300">
  </a>
  <a href="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-4.png" target="_blank">
    <img src="https://raw.githubusercontent.com/yasserbdj96/GitHubLineCounter/main/Screenshots/dashboard-4.png" alt="Preview" width="300">
  </a>
</p>

## 📝 License

This project is open source. Feel free to modify and distribute.

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## 📧 Support

For issues and questions, please open an issue on GitHub.

---

**Made with ❤️ for developers who love statistics**
