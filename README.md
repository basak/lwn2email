lwn2email
=========

Automatically email the latest subscriber-only LWN issue to an email
address (eg. an e-reader).

This tool requires the user to have an LWN subscription. If you think
you'll find find this script useful, please support LWN by buying a
subscription. I will respect LWN by not accepting pull requests that
allow the script to work without a subscription.

The script is a little dependent on LWN's formatting and may break if
they make changes. However, it has not broken yet since I wrote it
in 2013. Pull requests to improve formatting welcome.

Quick start
-----------

Dependencies: Python 3 and the lxml module (`sudo apt install
python3-lxml`).

You will need:

1. A working MTA on your system (`sendmail`). I use `msmtp`.
2. Your LWN username.
3. Your LWN password.
4. An email address (eg. your Send-to-Kindle email address).

Run:

    python3 lwn2email.py --username=... --password=... --address=...

For testing, you can use `--no-email`, which will write the newsletter
retrieve to standard output instead.

Configuration
-------------

Create `~/.config/lwn2email.conf` in INI-style, with a single
`[defaults]` section with `username`, `password` and `email` keys. For
example:

    [defaults]
    username=...
    password=...
    address=...

Now you can run the script without any parameters. In this mode, the
script will store a list of newsletters already emailed in
`~/.local/share/lwn2email/marks/` to avoid duplicates.

You can then add a call to the script to cron for Thursday morning.
Please be friendly to LWN and choose a random-ish time.
