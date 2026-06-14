import time
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com',
}


def bvid_to_aid(bvid):
    resp = requests.get(
        'https://api.bilibili.com/x/web-interface/view',
        params={'bvid': bvid},
        headers=HEADERS,
        timeout=10,
    )
    data = resp.json()
    if data['code'] != 0:
        raise ValueError(f"无法获取视频信息: {data['message']}")
    return data['data']['aid']


def fetch_comments(bvid, max_pages=5):
    """
    抓取指定BV号视频的顶层评论
    :param bvid: 视频BV号，如 BV1xx411c7mD
    :param max_pages: 最多抓取页数，每页20条
    :return: 评论文本列表
    """
    aid = bvid_to_aid(bvid)
    comments = []
    for page in range(1, max_pages + 1):
        resp = requests.get(
            'https://api.bilibili.com/x/v2/reply',
            params={'type': 1, 'oid': aid, 'pn': page, 'ps': 20, 'sort': 0},
            headers=HEADERS,
            timeout=10,
        )
        data = resp.json()
        if data['code'] != 0:
            print(f"第{page}页请求失败: {data['message']}")
            break
        replies = data['data'].get('replies') or []
        if not replies:
            break
        for reply in replies:
            text = reply['content']['message'].strip()
            if text:
                comments.append(text)
        print(f"已抓取第 {page} 页，累计 {len(comments)} 条")
        time.sleep(0.5)
    return comments
