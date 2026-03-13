from bs4 import BeautifulSoup, Tag

from brybox.core.models.email import EmailMeta

EXCLUDED_LINK_TEXT = [
    'browser',
    'click',
    'https',
    'just breath',
    'lab',
    'myotape',
    'oximeter',
    'paypal',
    'practical guide',
    'simply breathe',
    'sleep cycle',
    'snore lab',
    'the oxygen advantage',
    'this link',
    'unsubscribe',
    'venmo',
    'zeropod',
    'zoom.us',
]


def filter_audio_links(meta: EmailMeta) -> list[str]:

    soup = BeautifulSoup(meta.body_html, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        if not isinstance(a, Tag):
            continue
        href = a.get('href', '')
        links.append({'url': href, 'text': a.get_text(strip=True)})

    return [
        link['url']
        for link in links
        if link['text']
        and not link['text'].isdigit()
        and not any(bad.lower() in link['text'].lower() for bad in EXCLUDED_LINK_TEXT)
    ]
