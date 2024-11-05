# Import necessary libraries
import time
import random
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import csv
import locale
import os
from datetime import datetime
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

max_movies = 10

# Function to fetch movie details from TMDb
def fetch_movie_details(tmdb_id, api_key):
    movie_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}&append_to_response=keywords"
    response = requests.get(movie_url)

    if response.status_code == 200:
        movie_data = response.json()
        keywords = [keyword['name'] for keyword in movie_data['keywords']['keywords']]
        genres = [genre['name'] for genre in movie_data['genres']]
        return keywords, genres
    else:
        if response.status_code == 401:
            print("Check your API key.")
        return [], []

# Load blacklist and whitelist from CSV files
blacklist_path = r'C:\Users\bigba\aa Personal Projects\Letterboxd List Scraping\blacklist.csv'
whitelist_path = r'C:\Users\bigba\aa Personal Projects\Letterboxd List Scraping\whitelist.csv'

# Read titles and release years from the CSV files
whitelist = pd.read_csv(whitelist_path, header=None, names=['Title', 'Year'], encoding='utf-8')
blacklist = pd.read_csv(blacklist_path, header=None, names=['Title', 'Year'], usecols=[0, 1], encoding='utf-8')

# Function to add titles to blacklist, checking for duplicates
def add_to_blacklist(film_title, release_year, reason):
    if not any((film_title.lower() == row['Title'].lower() and release_year == row['Year']) for index, row in blacklist.iterrows()):
        with open(blacklist_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([film_title, release_year, reason])
        print(f"{film_title} ({release_year}) added to blacklist due to: {reason}")

# Set up Firefox options and service
options = Options()
options.headless = True
service = Service()
driver = webdriver.Firefox(service=service, options=options)

# Base URL of the Letterboxd films page
base_url = 'https://letterboxd.com/films/by/rating/'
film_data = []
rejected_data = []
unfiltered_approved = []
unfiltered_denied = []
total_titles = 0
valid_movies_count = 0
page_number = 1

# Dictionaries to count occurrences
director_counts = {}
actor_counts = {}
decade_counts = {}
genre_counts = {}
studio_counts = {}
language_counts = {}
country_counts = {}

# Insert your personal TMDB API key here
api_key = '420'

# Keywords/tags to filter out
filter_keywords = [
    'concert film', 'miniseries',
    'live performance', 'filmed theater', 'live theater', 
    'stand-up comedy', 'edited from tv series'
]

# Genres to filter out
filter_genres = ['Documentary']

# Function to check if a film is whitelisted
def is_whitelisted(film_title, release_year, whitelist):
    return any((film_title.lower() == row['Title'].lower() and release_year == row['Year']) for index, row in whitelist.iterrows())

# Function to extract runtime from Letterboxd
def extract_runtime(soup):
    scripts = soup.find_all('script')
    for script in scripts:
        if 'var filmData' in script.text:
            match = re.search(r'runTime:\s*(\d+)', script.text)
            if match:
                return int(match.group(1))
    return 0

# Create a set to track valid movies
added_movies = set()

# Loop until we find the specified number of valid movies
while valid_movies_count < max_movies:
    url = f'{base_url}page/{page_number}/'
    retries = 0  
    success = False
    
    while retries < 5 and not success:
        try:
            print(f'Sending GET request to: {url}')
            driver.get(url)
            print(f'Received response. Parsing HTML content...')
            time.sleep(2)
            
            # Verify the number of film containers equals 72
            film_containers = driver.find_elements(By.CSS_SELECTOR, 'div.react-component.poster')
            if len(film_containers) == 72:
                success = True
            else:
                print(f"Unexpected number of film containers ({len(film_containers)}). Retrying...")
                retries += 1
                time.sleep(30)
            
        except Exception as e:
            print(f"Connection error: {e}. Retrying in 30 seconds...")
            retries += 1
            time.sleep(30)
    
    if not success:
        print("Failed to retrieve the expected number of film containers after 5 attempts. Exiting.")
        break

    # Set a flag to track if we found any valid movies on the current page
    found_valid_movie_on_page = False

    for container in film_containers:
        film_title = container.get_attribute('data-film-name')
        film_url = container.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')

        # Extract the release year and rating count from the meta tag
        total_titles += 1
        response = requests.get(film_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        release_year_tag = soup.find('meta', property='og:title')
        release_year = None

        if release_year_tag:
            release_year_content = release_year_tag['content']
            release_year = release_year_content.split('(')[-1].strip(')')

        # Attempt to fetch the TMDb ID
        body_tag = soup.find('body')
        tmdb_id = body_tag.get('data-tmdb-id') if body_tag else None

        # Extract rating count from the JSON-like structure
        rating_count = 0
        scripts = soup.find_all('script')
        for script in scripts:
            if 'aggregateRating' in script.text:
                match = re.search(r'ratingCount":(\d+)', script.text)
                if match:
                    rating_count = int(match.group(1))
                    break

        # Check if the rating count is less than 1000
        if rating_count < 1000:
            print(f"{film_title} was not added due to insufficient ratings: {rating_count} ratings.")
            rejected_data.append([film_title, release_year, tmdb_id, 'Insufficient ratings (< 1000)'])
            continue

        # Check if the film is whitelisted, while looking for duplicates
        if is_whitelisted(film_title, release_year, whitelist):
            movie_identifier = (film_title.lower(), release_year)
            if movie_identifier not in added_movies:
                film_data.append({
                    'Title': film_title,
                    'Year': release_year,
                    'tmdbID': tmdb_id  # Use TMDb ID if available
                })
                added_movies.add(movie_identifier)
                valid_movies_count += 1
                found_valid_movie_on_page = True
                print(f"{film_title} was added due to being whitelisted. ({valid_movies_count}/{max_movies}) added to csv")

                # Extract directors
                director_elements = soup.select('span.directorlist a.contributor')
                for director in director_elements:
                    director_name = director.get_text(strip=True)
                    if director_name:
                        director_counts[director_name] = director_counts.get(director_name, 0) + 1

                # Extract actors without roles
                actor_elements = soup.select('#tab-cast .text-sluglist a.text-slug.tooltip')
                for actor in actor_elements:
                    actor_name = actor.get_text(strip=True)
                    if actor_name:
                        actor_counts[actor_name] = actor_counts.get(actor_name, 0) + 1

                # Extract decades
                decade_elements = soup.select_one('meta[property="og:title"]')
                if decade_elements:
                    content = decade_elements.get("content")
                    if content:
                        year = int(content.split('(')[-1].split(')')[0])
                        decade = (year // 10) * 10
                        decade_counts[decade] = decade_counts.get(decade, 0) + 1

                # Extract genres
                for heading in soup.select('#tab-genres h3'):
                    if "Genre" in heading.get_text() or "Genres" in heading.get_text():
                        sluglist = heading.find_next_sibling(class_='text-sluglist')
                        if sluglist:
                            genre_elements = sluglist.select('a.text-slug')
                            for genre in genre_elements:
                                genre_name = genre.get_text(strip=True)
                                if genre_name:
                                    genre_counts[genre_name] = genre_counts.get(genre_name, 0) + 1

                # Extract studios
                for heading in soup.select('#tab-details h3'):
                    if "Studio" in heading.get_text() or "Studios" in heading.get_text():
                        sluglist = heading.find_next_sibling(class_='text-sluglist')
                        if sluglist:
                            studio_elements = sluglist.select('a.text-slug')
                            for studio in studio_elements:
                                studio_name = studio.get_text(strip=True)
                                if studio_name:
                                    studio_counts[studio_name] = studio_counts.get(studio_name, 0) + 1

                # Extract languages
                for heading in soup.select('#tab-details h3'):
                    if "Language" in heading.get_text() or "Primary Language" in heading.get_text() or "Languages" in heading.get_text() or "Primary Languages" in heading.get_text():
                        sluglist = heading.find_next_sibling(class_='text-sluglist')
                        if sluglist:
                            language_elements = sluglist.select('a.text-slug')
                            for language in language_elements:
                                language_name = language.get_text(strip=True)
                                if language_name:
                                    language_counts[language_name] = language_counts.get(language_name, 0) + 1

                # Extract countries
                for heading in soup.select('#tab-details h3'):
                    if "Country" in heading.get_text() or "Countries" in heading.get_text():
                        sluglist = heading.find_next_sibling(class_='text-sluglist')
                        if sluglist:
                            country_elements = sluglist.select('a.text-slug')
                            for country in country_elements:
                                country_name = country.get_text(strip=True)
                                if country_name:
                                    country_counts[country_name] = country_counts.get(country_name, 0) + 1
                
                # Check if we have reached the maximum count
                if valid_movies_count >= max_movies:
                    print("Reached max_movies limit. Exiting.")
                    break
                continue

        # Check if the film is blacklisted
        if any((film_title.lower() == row['Title'].lower() and release_year == row['Year']) for index, row in blacklist.iterrows()):
            print(f"{film_title} was not added due to being blacklisted.")
            rejected_data.append([film_title, release_year, tmdb_id, 'Blacklisted'])
            continue

        # Extract runtime from Letterboxd
        runtime = extract_runtime(soup)

        # Filter out movies based on keywords and genres
        if tmdb_id:
            keywords, genres = fetch_movie_details(tmdb_id, api_key)

            if runtime < 40:
                print(f"{film_title} was not added due to a short runtime of {runtime} minutes.")
                rejected_data.append([film_title, release_year, tmdb_id, 'Short runtime'])
                add_to_blacklist(film_title, release_year, 'Short runtime')
                continue

            # Inside keyword filter check
            if any(keyword in keywords for keyword in filter_keywords):
                rejection_reason = f"Due to being a {', '.join(keyword for keyword in filter_keywords if keyword in keywords)}."
                print(f"{film_title} was not added {rejection_reason}")
                rejected_data.append([film_title, release_year, tmdb_id, rejection_reason])
                add_to_blacklist(film_title, release_year, rejection_reason)
                continue

            # Inside genre filter check
            if any(genre in genres for genre in filter_genres):
                rejection_reason = f"Due to being a {', '.join(genre for genre in filter_genres if genre in genres)}."
                print(f"{film_title} was not added {rejection_reason}")
                rejected_data.append([film_title, release_year, tmdb_id, rejection_reason])
                add_to_blacklist(film_title, release_year, rejection_reason)
                continue

        # If movie reaches here, it means it's a valid movie
        movie_identifier = (film_title.lower(), release_year)
        if movie_identifier not in added_movies:
            film_data.append({
                'Title': film_title,
                'Year': release_year,
                'tmdbID': tmdb_id  # Use TMDb ID if available
            })
            added_movies.add(movie_identifier)
            valid_movies_count += 1
            print(f"{film_title} was approved. ({valid_movies_count}/{max_movies})")
            unfiltered_approved.append([film_title, release_year, tmdb_id])

            # Extract directors
            director_elements = soup.select('span.directorlist a.contributor')
            for director in director_elements:
                director_name = director.get_text(strip=True)
                if director_name:
                    director_counts[director_name] = director_counts.get(director_name, 0) + 1

            # Extract actors without roles
            actor_elements = soup.select('#tab-cast .text-sluglist a.text-slug.tooltip')
            for actor in actor_elements:
                actor_name = actor.get_text(strip=True)
                if actor_name:
                    actor_counts[actor_name] = actor_counts.get(actor_name, 0) + 1

            # Extract decades
            decade_elements = soup.select_one('meta[property="og:title"]')
            if decade_elements:
                content = decade_elements.get("content")
                if content:
                    year = int(content.split('(')[-1].split(')')[0])
                    decade = (year // 10) * 10
                    decade_counts[decade] = decade_counts.get(decade, 0) + 1

            # Extract genres
            for heading in soup.select('#tab-genres h3'):
                if "Genre" in heading.get_text() or "Genres" in heading.get_text():
                    sluglist = heading.find_next_sibling(class_='text-sluglist')
                    if sluglist:
                        genre_elements = sluglist.select('a.text-slug')
                        for genre in genre_elements:
                            genre_name = genre.get_text(strip=True)
                            if genre_name:
                                genre_counts[genre_name] = genre_counts.get(genre_name, 0) + 1

            # Extract studios
            for heading in soup.select('#tab-details h3'):
                if "Studio" in heading.get_text() or "Studios" in heading.get_text():
                    sluglist = heading.find_next_sibling(class_='text-sluglist')
                    if sluglist:
                        studio_elements = sluglist.select('a.text-slug')
                        for studio in studio_elements:
                            studio_name = studio.get_text(strip=True)
                            if studio_name:
                                studio_counts[studio_name] = studio_counts.get(studio_name, 0) + 1

            # Extract languages
            for heading in soup.select('#tab-details h3'):
                if "Language" in heading.get_text() or "Primary Language" in heading.get_text() or "Languages" in heading.get_text() or "Primary Languages" in heading.get_text():
                    sluglist = heading.find_next_sibling(class_='text-sluglist')
                    if sluglist:
                        language_elements = sluglist.select('a.text-slug')
                        for language in language_elements:
                            language_name = language.get_text(strip=True)
                            if language_name:
                                language_counts[language_name] = language_counts.get(language_name, 0) + 1

            # Extract countries
            for heading in soup.select('#tab-details h3'):
                if "Country" in heading.get_text() or "Countries" in heading.get_text():
                    sluglist = heading.find_next_sibling(class_='text-sluglist')
                    if sluglist:
                        country_elements = sluglist.select('a.text-slug')
                        for country in country_elements:
                            country_name = country.get_text(strip=True)
                            if country_name:
                                country_counts[country_name] = country_counts.get(country_name, 0) + 1
                        
            # Check if we have reached the maximum count
            if valid_movies_count >= max_movies:
                print("Reached max_movies limit. Exiting.")
                break
        
    # Increment page number to scrape next page
    page_number += 1
    time.sleep(random.uniform(2, 4))

# Define chunk size and calculate the number of chunks
chunk_size = 1900
num_chunks = (len(film_data) + chunk_size - 1) // chunk_size

# Save data to CSV files
for i in range(num_chunks):
    start_idx = i * chunk_size
    end_idx = min((i + 1) * chunk_size, len(film_data))
    chunk_df = pd.DataFrame(film_data[start_idx:end_idx])
    chunk_df = chunk_df[['Title', 'Year', 'tmdbID']]
    chunk_df.to_csv(f'C:\\Users\\bigba\\aa Personal Projects\\Letterboxd List Scraping\\filtered_movie_titles{i + 1}.csv', index=False, encoding='utf-8')

# Define the output directory to ensure all files are in the same location
output_dir = r'C:\Users\bigba\aa Personal Projects\Letterboxd List Scraping'

# Save rejected data
rejected_file_path = os.path.join(output_dir, 'rejected_movies.csv')
with open(rejected_file_path, mode='w', newline='', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(['Title', 'Year', 'tmdbID', 'Reason'])
    writer.writerows(rejected_data)

# Save unfiltered approved data
unfiltered_approved_file_path = os.path.join(output_dir, 'unfiltered_approved.csv')
with open(unfiltered_approved_file_path, mode='w', newline='', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(['Title', 'Year', 'tmdbID'])
    writer.writerows(unfiltered_approved)

# Save unfiltered denied data
unfiltered_denied_file_path = os.path.join(output_dir, 'unfiltered_denied.csv')
with open(unfiltered_denied_file_path, mode='w', newline='', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(['Title', 'Year', 'tmdbID'])
    writer.writerows(unfiltered_denied)

# Helper function to get top 10 items
def get_top_10(counts_dict):
    return sorted(counts_dict.items(), key=lambda item: item[1], reverse=True)[:10]

# File path for stats output
stats_file_path = os.path.join(output_dir, 'filtered_titles_stats.txt')

# Function to format dates
def get_ordinal(n):
    """Return the ordinal representation of an integer (e.g., 1 -> '1st', 2 -> '2nd')."""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return str(n) + suffix

current_date = datetime.now()
formatted_date = current_date.strftime('%B ') + get_ordinal(current_date.day) + f", {current_date.year}"

# Write stats to text file
with open(stats_file_path, mode='w', encoding='utf-8') as file:
    file.write("The top 2,500 Narrative Feature Films on Letterboxd.\n\n")
    file.write(f"Last updated: {formatted_date}\n\n")
    file.write("Film eligibility criteria:\n")
    file.write("-- Must must have a minimum of 1,000 reviews on Letterboxd.\n")
    file.write("-- Cannot be a short film (minimum length of 40 minutes).\n")
    file.write("-- Cannot be a television miniseries.\n")
    file.write("-- Cannot be a compilation of short serials.\n")
    file.write("-- Cannot be a documentary.\n")
    file.write("-- Cannot be a non-narrative project (paint drying for 10 hours, a timelapse of the construction of a building, abstract images, etc).\n")
    file.write("-- Cannot be a recording of a live performance (stand-up specials, recordings of live theater, concert films, etc).\n")
    file.write("-- Cannot be a television special episode, though feature film spin-offs from television shows are allowed.\n")
    file.write("-- Feature film spin-offs from television shows must contain original material, not just recap or compilation of existing material.\n")
    file.write("-- Entries that have scores inflated because they share a name with a popular television show are removed, as I notice them.\n\n")

    # Directors
    file.write("The ten most appearing directors:\n")
    for director, count in get_top_10(director_counts):
        file.write(f"{director}: {count}\n")
    file.write("\n")

    # Actors
    file.write("The ten most appearing actors:\n")
    for actor, count in get_top_10(actor_counts):
        file.write(f"{actor}: {count}\n")
    file.write("\n")

    # Decades
    file.write("The ten most appearing decades:\n")
    for decade, count in get_top_10(decade_counts):
        file.write(f"{decade}: {count}\n")
    file.write("\n")

    # Genres
    file.write("The ten most appearing genres:\n")
    for genre, count in get_top_10(genre_counts):
        file.write(f"{genre}: {count}\n")
    file.write("\n")

    # Studios
    file.write("The ten most appearing studios:\n")
    for studio, count in get_top_10(studio_counts):
        file.write(f"{studio}: {count}\n")
    file.write("\n")

    # Languages
    file.write("The ten most appearing languages:\n")
    for language, count in get_top_10(language_counts):
        file.write(f"{language}: {count}\n")
    file.write("\n")

    # Countries
    file.write("The ten most appearing countries:\n")
    for country, count in get_top_10(country_counts):
        file.write(f"{country}: {count}\n")
    file.write("\n")

    # Link to web scraping code
    file.write("Link to web scraping code: https://github.com/bigbadraj/Letterboxd-Film-Scraping (It probably is super inefficient and messy, but it does run)\n\n")

    file.write("If you notice any movies you believe should/should not be included just let me know!")

print("Top 10 statistics saved to filtered_titles_stats.txt")

# Quit the driver after saving all files
driver.quit()

# Output totals
total_rejected = len(rejected_data)
total_unfiltered_approved = len(unfiltered_approved)
total_unfiltered_denied = len(unfiltered_denied)
print(f"Total movies scraped: {total_titles}")
print(f"Total accepted: {valid_movies_count}")
print(f"Total rejected: {total_rejected}")
print(f"Total unfiltered approved: {total_unfiltered_approved}")
print(f"Total unfiltered denied: {total_unfiltered_denied}")
print("Valid, rejected, and unfiltered approved/denied movies have been saved to CSV files.")