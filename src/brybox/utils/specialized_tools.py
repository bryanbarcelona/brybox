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


def filter_audio_links(links: list[dict[str, str]]) -> list[str]:

    return [
        link['url']
        for link in links
        if link['text']
        and not link['text'].isdigit()
        and not any(bad.lower() in link['text'].lower() for bad in EXCLUDED_LINK_TEXT)
    ]
