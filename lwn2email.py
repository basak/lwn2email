#!/usr/bin/python3

import argparse
import configparser
import email.generator
import email.mime.multipart
import email.mime.text
import errno
import hashlib
import http.cookiejar
import itertools
import io
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

import lxml.etree
from lxml.builder import E

# Any article matching this title is an LWN.net Weekly Edition article
MATCH_TITLE = re.compile(r'^(\[\$\] )?LWN.net Weekly Edition for')

# Transform LWN.net Weekly Edition article titles to a short form using this
# replacement (this stops it being too wide for display on e-book readers).
TITLE_TRANSFORMATION = (
    re.compile(r'^(?:\[\$\] )?LWN.net Weekly Edition for (.*)$'),
    r'LWN: \1'
)

USER_AGENT = 'https://github.com/basak/lwn2email'


def mkdir_p(path):
    """Create path if it doesn't exist already."""
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def html_to_email(html_fobj, email_fobj, title, destination_address):
    """Take an HTML input and construct an email with it attached.

    This produces an email suitable for sending to Amazon's personal Kindle
    email address, so that the file ends up as an available item on the Kindle.
    For this to work, the email appears to need to have a MIME part with a
    Content-Disposition of "attachment" with the filename set to something
    whose root (the part before the '.') ends up as the document title on the
    Kindle. This behaviour is hardcoded into this function.

    title: used for both the subject line and the root of the attachment
        filename
    destination_address: this ends up in the To: header

    The result is bytes written to email_fobj in a form suitable for writing
    to a Unix "sendmail -oi -t" invocation.
    """

    outer = email.mime.multipart.MIMEMultipart()
    inner = email.mime.text.MIMEText(html_fobj.read(), 'html', 'utf-8')
    inner.add_header(
        'Content-Disposition', 'attachment', filename='%s.html' % title)
    outer.attach(inner)
    outer.add_header('To', destination_address)
    outer.add_header('Subject', title)
    outer.add_header('User-Agent', USER_AGENT)
    email.generator.BytesGenerator(email_fobj, mangle_from_=False).flatten(
        outer)


def get_lwn_url(lwn_url, username, password):
    """Authenticate with lwn.net and retrieve the given URL.

    Use this instead of a simple URL fetch to fetch subscriber-only content,
    which on LWN is kept behind session cookie -based authentication.
    """

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    r = opener.open(
        urllib.request.Request(
            'https://lwn.net/login',
            urllib.parse.urlencode(
                {'Username': username, 'Password': password, 'target': '/'}
            ).encode('utf-8'),
            {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
             'User-Agent': USER_AGENT}
        )
    )
    if r.getcode() != 200:
        raise RuntimeError("LWN login failure")
    r = opener.open(
        urllib.request.Request(
            lwn_url,
            headers={'User-Agent': USER_AGENT},
        )
    )
    if r.getcode() != 200:
        raise RuntimeError("LWN page fetch problem")
    return r


def to_https(url):
    """Convert any http:// URL to an equivalent https:// URL."""

    if url.startswith('http://'):
        return 'https://' + url[7:]
    else:
        return url


def lwn_weekly_urls():
    """Read LWN's Features RSS feed and return LWN Weekly Edition data.

    Yields pairs of (url, title) filtered for LWN.net Weekly Editions only. The
    URLs are converted to the "bigpage printable" format using magic knowledge
    of LWN's URL scheme.

    LWN's RSS feed seems to use http:// URLs even though https:// URLs are
    available, so this function converts URLs to https:// URLs before returning
    them.
    """

    r = urllib.request.urlopen(
        urllib.request.Request(
            'https://lwn.net/headlines/Features',
            headers={'User-Agent': USER_AGENT},
        )
    )
    if r.getcode() != 200:
        raise RuntimeError("LWN feed fetch error")

    tree = lxml.etree.parse(r)
    root = tree.getroot()
    for item in root.findall('{http://purl.org/rss/1.0/}item'):
        title_element = item.find('{http://purl.org/rss/1.0/}title')
        link_element = item.find('{http://purl.org/rss/1.0/}link')
        if title_element is None or link_element is None:
            continue
        if (MATCH_TITLE.match(title_element.text) and
                link_element.text.endswith('/rss')):
            url = to_https(link_element.text[:-3] + 'bigpage?format=printable')
            title = TITLE_TRANSFORMATION[0].sub(
                TITLE_TRANSFORMATION[1], title_element.text)
            yield (url, title)


def mark_file(key):
    """Convert an arbitrary string key into a unique filename.

    Since URLs contain '/' characters, they don't make suitable filenames
    as-is. To represent a URL in a filename, it's easiest to just hash it and
    use the hex result.
    """

    return hashlib.md5(key.encode('utf-8')).hexdigest()


def is_marked(key, state_dir):
    """Determine if key is represented in state_dir."""

    if state_dir:
        return os.path.exists(os.path.join(state_dir, mark_file(key)))
    else:
        return False


def mark(key, state_dir):
    """Mark key as represented in state_dir."""

    if not state_dir:
        return
    with open(os.path.join(state_dir, mark_file(key)), 'w') as f:
        f.write("%s\n" % key)


def first_unmarked_key(elements, key_function, state_dir):
    """Find the first unmarked key in a sequence of elements.

    key_function is a callable that must extract the key out of an element.
    """

    unmarked_keys = itertools.filterfalse(
        lambda element: is_marked(key_function(element), state_dir), elements)
    return next(iter(unmarked_keys))


def default_xdg_dir(env_var, home_path):
    """Determine an XDG directory using the specification rules.

    See: http://standards.freedesktop.org/basedir-spec/basedir-spec-0.6.html

    env_var is the XDG_* environment variable we're looking for.

    home_path is a sequence of path elements from the home directory that
    should be used if the XDG_* environment variable is not found.

    Returns the contents of env_var if it is available, or the absolute home
    directory path if it is not defined.
    """

    xdg_data_home = os.getenv(env_var)
    if xdg_data_home is not None:
        return xdg_data_home

    home = os.getenv('HOME')
    if home is None:
        raise RuntimeError("Cannot find user home directory")
    return os.path.join(home, *home_path)


def get_config():
    """Parse program arguments using a configuration file for defaults."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--marks-directory',
        default=os.path.join(
            default_xdg_dir(
                'XDG_DATA_DIR',
                ['.local', 'share']
            ),
            'lwn2email', 'marks'
        )
    )
    parser.add_argument('--no-email', action='store_true')
    parser.add_argument('--address')
    parser.add_argument('--username')
    parser.add_argument('--password')

    config_path = default_xdg_dir('XDG_CONFIG_HOME', ['.config'])
    config = configparser.ConfigParser()
    config.read(os.path.join(config_path, 'lwn2email.conf'))
    try:
        parser.set_defaults(**dict(config.items('defaults')))
    except configparser.NoSectionError:
        pass
    if not config.sections():
        # If no configuration file was used, then do not use marks by default
        parser.set_defaults(marks_directory=None)
    result = parser.parse_args()
    if not all([result.address, result.username, result.password]):
        parser.error(
            "You must specify all of (--address, --username, --password) " +
            "or specify these in a configuration file.")
    return result


def fix_html(html_fobj):
    parser = lxml.etree.HTMLParser()
    root = lxml.etree.parse(html_fobj, parser).getroot()
    main = root.xpath("//div[@class='ArticleText']")[0]

    root = E.html(
        E.head(root.xpath("//head/title")[0]),
        E.body(main),
    )

    for element in root.xpath("//p[@class='Cat1HL']"):
        element.tag = 'h1'

    output_bytes = lxml.etree.tostring(root, pretty_print=True, method='html')
    return output_bytes.decode('utf-8')


def main():
    config = get_config()
    if config.marks_directory:
        mkdir_p(config.marks_directory)

    url_title_pairs = lwn_weekly_urls()
    url, title = first_unmarked_key(
        url_title_pairs, lambda pair: pair[0], config.marks_directory)
    html_fobj = get_lwn_url(
        url, username=config.username, password=config.password)
    fixed_html = fix_html(html_fobj)
    if not config.no_email:
        sendmail = subprocess.Popen(
            ['sendmail', '-oi', '-t'], stdin=subprocess.PIPE)
        html_to_email(
            io.StringIO(fixed_html), sendmail.stdin, title,
            destination_address=config.address)
        sendmail.stdin.close()
        if sendmail.wait():
            raise RuntimeError(
                "sendmail returned with exit %d." % sendmail.returncode)
    else:
        sys.stdout.write(fixed_html)
    mark(url, config.marks_directory)


if __name__ == '__main__':
    main()
