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
    context.log("Function started")
    if context.req.method == "GET":
        context.log("GET request received")
        return context.res.send(
            "<html><body><h1>Welcome to the News Search API</h1></body></html>",
            200,
            {"content-type": "text/html; charset=utf-8"},
        )

    context.log("POST request received")
    context.log(f"Received body: {context.req.body}")
    try:
        body = json.loads(context.req.body) if isinstance(context.req.body, str) else context.req.body
        search_term = body["search_term"]
        target_date = body["target_date"]
        context.log(f"Parsed request body - search_term: {search_term}, target_date: {target_date}")
    except (json.JSONDecodeError, KeyError) as e:
        context.log(f"Error parsing request body: {str(e)}")
        return context.res.json({"ok": False, "error": f"Invalid request body: {str(e)}"}, 400)

    search_url = "https://api.bing.microsoft.com/v7.0/news/search"
    context.log(f"Search URL: {search_url}")

    def scrape_article(url, target_date, max_retries=2):
        context.log(f"Scraping article: {url}")
        retry_count = 0
        article_data = []

        while retry_count < max_retries:
            try:
                article = Article(url, language='en')
                article.download()
                article.parse()

                if len(article.text) < 10:
                    context.log(f"Article text too short, skipping: {url}")
                    break

                article_language = detect(article.text)
                context.log(f"Detected language: {article_language}")
                if article_language == 'en':
                    if (
                        article.publish_date
                        and article.publish_date.date() > pd.to_datetime(target_date).date()
                    ):
                        context.log(f"Article added: {article.title}")
                        article_data.append({
                            'title': article.title,
                            'body': article.text[:500] + "...",  # Truncated for log readability
                            'author': article.authors if article.authors else "No author found",
                            'publish_date': article.publish_date.strftime('%Y-%m-%d')
                        })
                    break
                else:
                    context.log(f"Non-English article, skipping: {url}")
                    break
            except ArticleException as ae:
                context.log(f"ArticleException: {str(ae)}, retrying...")
                retry_count += 1
                time.sleep(2)
                continue
            except Exception as e:
                context.log(f"Unexpected error in scraping: {str(e)}")
                break

        if not article_data:
            context.log(f"No data scraped for: {url}")
            return None
        return article_data

    def get_gemini_response(prompt):
        context.log("Generating summary with Gemini")
        genai.configure(api_key='AIzaSyC4D2itDTFx27b6BuewuF3W3cPXgG856q4')
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        context.log("Summary generated")
        return response.text

    try:
        context.log("Fetching news from Bing")
        headers = {"Ocp-Apim-Subscription-Key": 'a04bdca342a948669e9a2c2a1b9d2a83'}
        params = {"q": search_term}
        response = requests.get(search_url, headers=headers, params=params)
        response.raise_for_status()
        search_results = response.json()
        context.log(f"Received {len(search_results.get('value', []))} results from Bing")

        news_items = []
        for article in search_results["value"]:
            context.log(f"Processing article: {article.get('name', 'Unnamed article')}")
            scraped_data = scrape_article(article["url"], target_date)
            if scraped_data:
                for item in scraped_data:
                    prompt = f"Your task is to generate a 50-word summary for the following news: Title: {item['title']} Body:{item['body'][:500]}..."
                    summary = get_gemini_response(prompt)
                    item['summary'] = summary
                news_items.extend(scraped_data)
            else:
                context.log("Using basic info from Bing API")
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

        context.log(f"Processed {len(news_items)} news items")
        return context.res.json({"ok": True, "news_items": news_items}, 200)

    except requests.exceptions.RequestException as e:
        context.log(f"RequestException: {str(e)}")
        return context.res.json({"ok": False, "error": f"Error fetching news: {str(e)}"}, 500)
    except KeyError as e:
        context.log(f"KeyError: {str(e)}")
        return context.res.json({"ok": False, "error": f"Error parsing response: {str(e)}"}, 500)
    except Exception as e:
        context.log(f"Unexpected error: {str(e)}")
        return context.res.json({"ok": False, "error": f"An unexpected error occurred: {str(e)}"}, 500)
