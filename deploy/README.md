# Server launch

The public DNS record for `community.arynwood.com` should point at this host.

The templates assume Debian or Ubuntu, an `arynwood` system user, Nginx, and Certbot.

```bash
sudo useradd --system --home /opt/arynwood-community --shell /usr/sbin/nologin arynwood || true
sudo mkdir -p /opt/arynwood-community /var/www/acme
sudo chown -R arynwood:arynwood /opt/arynwood-community
```

Copy the sanitized client bundle to `/opt/arynwood-community`, extract it, copy `.env.example` to `.env`, and set:

```env
COMMUNITY_HOSTS=community.arynwood.com
COMMUNITY_ORIGIN=https://community.arynwood.com
COMMUNITY_SECURE_COOKIE=1
```

Run `./setup.sh`, then install `arynwood-community.service` into `/etc/systemd/system/` and enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now arynwood-community
sudo systemctl status arynwood-community
```

Install the Nginx template at `/etc/nginx/sites-available/community.arynwood.com`, link it into `sites-enabled`, test, and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d community.arynwood.com
```

Check `https://community.arynwood.com/api/health`, then create the first account. Keep `.env`, `data/`, and `nkn/wallet.json` private and backed up.
