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
from appwrite.client import Client
from appwrite.services.functions import Functions

def main(context, res):
    # Handle GET request
    if context.req.method == "GET":
        return res.send(
            "This function handles news fetching and summarization. Use POST method to interact.",
            200,
            {"content-type": "text/plain; charset=utf-8"},
        )

    # Handle POST request
    if context.req.method == "POST":
        # Initialize Appwrite client
        client = Client()
        client.set_endpoint(context.env.get('APPWRITE_ENDPOINT'))
        client.set_project(context.env.get('APPWRITE_PROJECT_ID'))
        client.set_key(context.env.get('APPWRITE_API_KEY'))

        # Configuration
        bing_subscription_key = context.env.get('BING_SUBSCRIPTION_KEY')
        google_api_key = context.env.get('GOOGLE_API_KEY')
        search_url = "https://api.bing.microsoft.com/v7.0/news/search"
        
        # Get parameters from request
        try:
            data = json.loads(context.req.body)
            search_term = data.get('search_term', 'Microsoft')
            target_date = data.get('target_date', (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
        except json.JSONDecodeError:
            return res.json({"ok": False, "error": "Invalid JSON in request body"}, 400)

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
            search_results = json.loads(response.text)

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

            return res.json({
                'ok': True,
                'news_items': news_items
            }, 200)

        except requests.exceptions.RequestException as e:
            return res.json({
                'ok': False,
                'error': f'Error fetching news: {str(e)}'
            }, 500)
        except KeyError as e:
            return res.json({
                'ok': False,
                'error': f'Error parsing response: {str(e)}'
            }, 500)
        except Exception as e:
            return res.json({
                'ok': False,
                'error': f'An unexpected error occurred: {str(e)}'
            }, 500)

    # Handle other HTTP methods
    return res.json({
        'ok': False,
        'error': 'Method not allowed'
    }, 405)
