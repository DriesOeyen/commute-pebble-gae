#!/usr/bin/env python27
# -*- coding: utf-8 -*-
"""Commute billing service implemented in Flask."""

import flask

app = flask.Flask(__name__)


@app.route('/test')
def test():
    return "Test!"
