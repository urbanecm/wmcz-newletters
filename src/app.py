#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import yaml
from flask import redirect, request, jsonify, render_template, url_for, \
    make_response
from flask import Flask
import requests
from urllib.parse import urljoin
from flask_jsonlocale import Locales
from flask_mwoauth import MWOAuth
from SPARQLWrapper import SPARQLWrapper, JSON
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import simplejson as json

app = Flask(__name__, static_folder='../static')

# Load configuration from YAML file
__dir__ = os.path.dirname(__file__)
app.config.update(
    yaml.safe_load(open(os.path.join(__dir__, os.environ.get(
        'FLASK_CONFIG_FILE', 'config.yaml')))))

db = SQLAlchemy(app)
migrate = Migrate(app, db)

mwoauth = MWOAuth(
    consumer_key=app.config.get('CONSUMER_KEY'),
    consumer_secret=app.config.get('CONSUMER_SECRET'),
    base_url=app.config.get('OAUTH_MWURI'),
)
app.register_blueprint(mwoauth.bp)

class Mailgun(requests.Session):
    def __init__(self, *args, **kwargs):
        super(Mailgun, self).__init__(*args, **kwargs)
        self.prefix_url = 'https://api.mailgun.net/v3/'
        self.api_key = app.config.get('MAILGUN_API')
    
    def request(self, method, url, *args, **kwargs):
        url = urljoin(self.prefix_url, url)
        return super(Mailgun, self).request(method, url, auth=('api', self.api_key), *args, **kwargs)

def logged():
    return mwoauth.get_current_user() is not None

@app.context_processor
def inject_base_variables():
    return {
        "logged": logged(),
        "username": mwoauth.get_current_user(),
    }

@app.before_request
def force_login():
    if not logged() and request.path != "/login" and not request.path.startswith("/oauth-callback"):
        return render_template('login.html')

@app.route('/', methods=['GET', 'POST'])
def index():
    m = Mailgun()
    if request.method == 'POST':
        vars = {}
        for i in request.form.getlist('variable'):
            vars[request.form.get('variable-%s' % i)] = request.form.get('value-%s' % i)
        data = {
            'from': request.form.get('from'),
            'subject': request.form.get('subject'),
            'template': request.form.get('template'),
            'to': request.form.get('list'),
            'o:tag': request.form.get('template'),
            'h:X-Mailgun-Variables': json.dumps(vars)
        }
        if request.form.get('replyto', '') != "":
            data['h:Reply-To'] = request.form.get('replyto')
        r = m.post(
            '%s/messages' % app.config.get('MAILGUN_DOMAIN'),
            data=data,
            files=[
                ('attachment', (request.files['attachment'].filename, request.files['attachment']))
            ]
        )
        print(r.json())
    lists = m.get('lists').json()['items']
    tmpls = m.get('%s/templates' % app.config.get('MAILGUN_DOMAIN')).json().get('items', [])
    return render_template('tool.html', lists=lists, tmpls=tmpls)

@app.route('/maillists')
def maillists():
    m = Mailgun()
    lists = m.get('lists').json()['items']
    return render_template('maillists.html', lists=lists)

@app.route('/maillists/<mail>', methods=['GET', 'POST'])
def maillist(mail):
    m = Mailgun()
    if request.method == 'POST':
        if request.form.get('addresses') is not None:
            members = []
            vars = {}
            if request.form.get('variable') != '':
                vars = {
                    request.form.get('variable'): request.form.get('value')
                }
            for row in request.form.get('addresses').split('\n'):
                members.append({
                    'address': row,
                    'vars': vars
                })
            r = m.post(
                'lists/%s/members.json' % mail,
                data={
                    'upsert': True,
                    'members': json.dumps(members)
                }
            )
            print(r.json())
        else:
            vars = {}
            if request.form.get('variable', "") != "":
                vars[request.form.get('variable')] = request.form.get('value')
            m.post(
                'lists/%s/members' % mail,
                data={
                    'address': request.form.get('address'),
                    'name': request.form.get('name'),
                    'vars': json.dumps(vars)
                }
            )
    list = m.get('lists/%s' % mail).json()['list']
    members = m.get('lists/%s/members' % mail).json().get('items', [])
    return render_template('maillist.html', list=list, members=members)

@app.route('/maillists/<mail>/<member>', methods=['GET', 'POST'])
def maillist_member(mail, member):
    m = Mailgun()
    if request.method == 'POST':
        if request.form.get('type') == 'update':
            vars = {}
            for var in request.form.getlist('variable'):
                name = request.form.get('variable-%s' % var)
                if name != "":
                    vars[name] = request.form.get('value-%s' % var)
            if request.form.get('variable-new', '') != "":
                vars[request.form.get('variable-new')] = request.form.get('value-new')
            m.put('lists/%s/members/%s' % (mail, member), data={
                'name': request.form.get('name'),
                'address': request.form.get('address'),
                'vars': json.dumps(vars)
            })
        elif request.form.get('type') == 'delete':
            m.delete('lists/%s/members/%s' % (mail, member))
            return redirect(url_for('maillist', mail=mail))
    list = m.get('lists/%s' % mail).json()['list']
    member = m.get('lists/%s/members/%s' % (mail, member)).json()['member']
    return render_template('maillist_member.html', list=list, member=member)

@app.route('/templates')
def templates():
    m = Mailgun()
    tmpls = m.get('%s/templates' % app.config.get('MAILGUN_DOMAIN')).json().get('items', [])
    return render_template('templates.html', tmpls=tmpls)

@app.route('/templates/<template>')
def template(template):
    m = Mailgun()
    tmpl = m.get('%s/templates/%s/versions' % (app.config.get('MAILGUN_DOMAIN'), template)).json()['template']
    return render_template('template.html', tmpl=tmpl)

@app.route('/templates/<template>/<version>')
def template_version(template, version):
    m = Mailgun()
    tmpl = m.get('%s/templates/%s/versions/%s' % (app.config.get('MAILGUN_DOMAIN'), template, version)).json()['template']
    return render_template('template_version.html', tmpl=tmpl)

@app.route('/templates/<template>/<version>/content')
def template_version_content(template, version):
    m = Mailgun()
    tmpl = m.get('%s/templates/%s/versions/%s' % (app.config.get('MAILGUN_DOMAIN'), template, version)).json()['template']
    return tmpl['version']['template']

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
