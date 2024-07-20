import numpy as np
import google.generativeai as genai
import os
import time
from datetime import datetime, timedelta
from newspaper import Article
from newspaper.article import ArticleException
from langdetect import detect
import pandas as pd
import requests
import json

def main(context):
    if context.req.method == "GET":
        # Since we can't use get_static_file, we'll return a simple message
        return context.res.send(
            "<html><body><h1>Welcome to the News Search API</h1></body></html>",
            200,
            {"content-type": "text/html; charset=utf-8"},
        )

    # Implement throw_if_missing functionality directly
    required_fields = ["search_term", "target_date"]
    for field in required_fields:
        if field not in context.req.body:
            return context.res.json({"ok": False, "error": f"Missing required field: {field}"}, 400)

    search_term = context.req.body["search_term"]
    target_date = context.req.body["target_date"]

    # Configuration
    bing_subscription_key = context.env.get('a04bdca342a948669e9a2c2a1b9d2a83')
    google_api_key = context.env.get('AIzaSyC4D2itDTFx27b6BuewuF3W3cPXgG856q4')
    search_url = "https://api.bing.microsoft.com/v7.0/news/search"

    def scrape_article(url, target_date, max_retries=2):
        retry_count = 0
        article_data = []

        while retry_count < max_retries:
            try:
                article = Article(url, language='en')
                article.download()
                article.parse()

                if len(article.text) < 10:
                    break

                article_language = detect(article.text)
                if article_language == 'en':
                    if (
                        article.publish_date
                        and article.publish_date.date() > pd.to_datetime(target_date).date()
                    ):
                        article_data.append({
                            'title': article.title,
                            'body': article.text,
                            'author': article.authors if article.authors else "No author found",
                            'publish_date': article.publish_date.strftime('%Y-%m-%d')
                        })
                    break
                else:
                    break
            except ArticleException as ae:
                retry_count += 1
                time.sleep(2)
                continue
            except Exception as e:
                break

        if not article_data:
            return None
        return article_data

    def get_gemini_response(prompt):
        genai.configure(api_key=google_api_key)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text

    try:
        # Fetch news from Bing
        headers = {"Ocp-Apim-Subscription-Key": bing_subscription_key}
        params = {"q": search_term}
        response = requests.get(search_url, headers=headers, params=params)
        response.raise_for_status()
        search_results = response.json()

        news_items = []
        for article in search_results["value"]:
            scraped_data = scrape_article(article["url"], target_date)
            if scraped_data:
                for item in scraped_data:
                    prompt = f"Your task is to generate a 50-word summary for the following news: Title: {item['title']} Body:{item['body']}"
                    summary = get_gemini_response(prompt)
                    item['summary'] = summary
                news_items.extend(scraped_data)
            else:
                # If scraping failed, use basic info from Bing API and summarize the description
                basic_info = {
                    "title": article.get("name", "No title"),
                    "body": article.get("description", "No description"),
                    "url": article["url"],
                    "publish_date": article.get("datePublished", "Unknown date")
                }
                prompt = f"Your task is to generate a 50-word summary for the following news: Title: {basic_info['title']} Body:{basic_info['body']}"
                summary = get_gemini_response(prompt)
                basic_info['summary'] = summary
                news_items.append(basic_info)

        return context.res.json({"ok": True, "news_items": news_items}, 200)

    except requests.exceptions.RequestException as e:
        return context.res.json({"ok": False, "error": f"Error fetching news: {str(e)}"}, 500)
    except KeyError as e:
        return context.res.json({"ok": False, "error": f"Error parsing response: {str(e)}"}, 500)
    except Exception as e:
        return context.res.json({"ok": False, "error": f"An unexpected error occurred: {str(e)}"}, 500)
