#!/usr/bin/env python
# coding:utf-8
#   |                                                          |
# --+----------------------------------------------------------+--
#   |   Code by : yasserbdj96                                  |
#   |   Email   : yasser.bdj96@gmail.com                       |
#   |   Github  : https://github.com/yasserbdj96               |
#   |   BTC     : bc1q2dks8w8uurca5xmfwv4jwl7upehyjjakr3xga9   |
# --+----------------------------------------------------------+--  
#   |        all posts #yasserbdj96 ,all views my own.         |
# --+----------------------------------------------------------+--
#   |                                                          |

#START{
import os
from github import Github
import json
import sys
import re
import time
from tabulate import tabulate

def clone_repos(GITHUB_ACCESS_TOKEN,GITHUB_USERNAME):
    g = Github(GITHUB_ACCESS_TOKEN)

    # Create "repos" folder if it doesn't exist
    if not os.path.exists("repos"):
        os.makedirs("repos")

    # Create "public" and "private" folders within "repos"
    public_folder = os.path.join("repos", "public")
    private_folder = os.path.join("repos", "private")
    if not os.path.exists(public_folder):
        os.makedirs(public_folder)
    if not os.path.exists(private_folder):
        os.makedirs(private_folder)

    # Clone all public repositories owned by the user
    for repo in g.get_user().get_repos(affiliation='owner'):
        if not repo.private:
            os.makedirs(os.path.join(public_folder), exist_ok=True)
            if os.path.exists(os.path.join(public_folder, repo.name)):
                pass
            else:
                os.system(f"git clone {repo.clone_url} {os.path.join(public_folder, repo.name)}")
                os.system(f"rm -rf {os.path.join(public_folder, repo.name, '.git')}")

    # Clone all private repositories owned by the user
    for repo in g.get_user().get_repos(affiliation='owner'):
        if repo.private:
            os.makedirs(os.path.join(private_folder), exist_ok=True)
            # Include the access token and username in the clone URL to avoid being prompted for them
            if os.path.exists(os.path.join(private_folder, repo.name)):
                pass
            else:
                os.system(f"git clone https://{GITHUB_USERNAME}:{GITHUB_ACCESS_TOKEN}@{repo.clone_url.split('://')[1]} {os.path.join(private_folder, repo.name)}")
                os.system(f"rm -rf {os.path.join(private_folder, repo.name, '.git')}")


def is_binary_file(filepath):
    with open(filepath, 'rb') as f:
        chunk = f.read(1024)
        if b'\0' in chunk:
            return True
        return False

def count_lines(filepath, language):
    total_lines = 0
    code_lines = 0
    comment_lines = 0
    empty_lines = 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            total_lines += 1
            line = line.strip()
            if not line:
                empty_lines += 1
            elif re.match(language['comment_regex'], line):
                comment_lines += 1
            else:
                code_lines += 1
    return (total_lines, code_lines, comment_lines, empty_lines)

def get_language(filepath, languages):
    for language in languages.values():
        for extension in language['extensions']:
            if filepath.endswith(extension):
                return language
    return None

def get_filetypes(dirpath):
    filetypes = {}
    for root, dirs, files in os.walk(dirpath):
        for file in files:
            filepath = os.path.join(root, file)
            if not is_binary_file(filepath):
                ext = os.path.splitext(file)[1]
                if ext not in filetypes:
                    filetypes[ext] = 0
                filetypes[ext] += 1
    return filetypes

def main():
    dirpath = "./repos"
    if not os.path.isdir(dirpath):
        print("Invalid directory path")
        return

    with open("languages.json") as f:
        languages = json.load(f)

    total_lines = 0
    total_code_lines = 0
    total_comment_lines = 0
    total_empty_lines = 0
    lang_lines = {}
    filetypes = get_filetypes(dirpath)
    
    new_dict = {}
    for key in languages:
        name = languages[key]["name"].upper()
        new_dict[name] = 0

    for root, dirs, files in os.walk(dirpath):
        for file in files:
            filepath = os.path.join(root, file)
            if not is_binary_file(filepath):
                language = get_language(filepath, languages)
                if language:
                    (total, code, comment, empty) = count_lines(filepath, language)
                    total_lines += total
                    total_code_lines += code
                    total_comment_lines += comment
                    total_empty_lines += empty
                    lang_name = language["name"].upper()
                    new_dict[f"{lang_name}"] += 1
                    if lang_name not in lang_lines:
                        lang_lines[lang_name] = {'total': 0, 'code': 0, 'comment': 0, 'empty': 0}
                    lang_lines[lang_name]['total'] += total
                    lang_lines[lang_name]['code'] += code
                    lang_lines[lang_name]['comment'] += comment
                    lang_lines[lang_name]['empty'] += empty

    total_files = sum(new_dict.values())

    #all_var=""
    #all_var+="Language    Files    Total Lines      Code Lines       Comment Lines     Empty Lines"+"\n"
    #all_var+="-"*84+"\n"
    data = []
    for lang, lines in lang_lines.items():
        total = lines['total']
        code = lines['code']
        comment = lines['comment']
        empty = lines['empty']

        data.append({'Language': f'{lang}', 'Files': new_dict[f"{lang}"], 'Total Lines': total, 'Code Lines': code, 'Comment Lines': comment, 'Empty Lines': empty})


        #all_var+="{:<12}{:<9}{:<17}{:<17}{:<19}{}".format(lang, new_dict[f"{lang}"], total, code, comment, empty)+"\n"

    #all_var+="-"*84+"\n"
    #all_var+="{:<12}{:<9}{:<17}{:<17}{:<19}{}".format("TOTAL", total_files, total_lines, total_code_lines, total_comment_lines, total_empty_lines)
    #data.append({'Language': 'TOTAL', 'Files': total_files, 'Total Lines': total_lines, 'Code Lines': total_code_lines, 'Comment Lines': total_comment_lines, 'Empty Lines': total_empty_lines})
    return data

def format_table(data):
    headers = ['Language', 'Files', 'Total Lines', 'Code Lines', 'Comment Lines', 'Empty Lines']
    table = []
    for d in data:
        row = [d['Language'], d['Files'], d['Total Lines'], d['Code Lines'], d['Comment Lines'], d['Empty Lines']]
        table.append(row)
    table.append(['TOTAL', sum(d['Files'] for d in data), sum(d['Total Lines'] for d in data),
                  sum(d['Code Lines'] for d in data), sum(d['Comment Lines'] for d in data), sum(d['Empty Lines'] for d in data)])
    return tabulate(table, headers, tablefmt='pipe')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: python {os.path.basename(__file__)} 'GITHUB_ACCESS_TOKEN' 'GITHUB_USERNAME'")
        exit()
    else:
        clone_repos(sys.argv[1],sys.argv[2])
        
        all_var=format_table(main())
        with open('README.md', 'w') as f:
            # Get current date and time in seconds since the epoch
            seconds_since_epoch = time.time()

            # Format the value as a date and time string
            date_time_string = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds_since_epoch))

            #   Print the value
            print(date_time_string)
            f.write(all_var)
            f.write("\n\nLast Update: "+date_time_string)

        print(all_var)
#}END.