from functools import wraps
from flask import request, jsonify
from config import API_KEY

def authenticate(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not API_KEY:
            return jsonify({"message": "Server misconfigured: API_KEY not set"}), 500

        api_key = request.headers.get('X-API-Key')
        if api_key != API_KEY:
            return jsonify({"message": "Unauthorized"}), 401
        return func(*args, **kwargs)
    return wrapper
