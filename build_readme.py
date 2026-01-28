import re
import os
import pathlib
import json
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

root = pathlib.Path(__file__).parent.resolve()
TOKEN = os.environ.get("TOKEN", "")

def replace_chunk(content: str, marker: str, chunk: str, inline: bool = False) -> str:
    """Replace a chunk of text between markers."""
    pattern = re.compile(
        rf"<!-- {marker} starts -->.*<!-- {marker} ends -->",
        re.DOTALL,
    )
    if not inline:
        chunk = f"\n{chunk}\n"
    new_chunk = f"<!-- {marker} starts -->{chunk}<!-- {marker} ends -->"
    return pattern.sub(new_chunk, content)

def make_query(after_cursor: Optional[str] = None) -> str:
    """Create the GitHub GraphQL query."""
    after = f'"{after_cursor}"' if after_cursor else "null"
    return """
query {
  user(login: "fulln") {
    repositories(first: 100, privacy: PUBLIC, after:AFTER) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        description
        url
        releases(last:1) {
          totalCount
          nodes {
            name
            publishedAt
            url
          }
        }
      }
    }
  }
}
""".replace("AFTER", after)

def fetch_releases(client: httpx.Client, oauth_token: str) -> List[Dict[str, Any]]:
    """Fetch recent releases from GitHub via GraphQL."""
    releases = []
    repo_names = set()
    has_next_page = True
    after_cursor = None

    while has_next_page:
        response = client.post(
            "https://api.github.com/graphql",
            json={"query": make_query(after_cursor)},
            headers={"Authorization": f"Bearer {oauth_token}"},
        )
        response.raise_for_status()
        data = response.json()
        
        # Log for debugging
        if "errors" in data:
            print(f"GraphQL Errors: {data['errors']}")
        if "data" not in data or "user" not in data["data"]:
            print(f"Unexpected data structure: {data}")
            break

        result = data["data"]["user"]["repositories"]
        for repo in result["nodes"]:
            if repo["releases"]["totalCount"] and repo["name"] not in repo_names:
                repo_names.add(repo["name"])
                release_node = repo["releases"]["nodes"][0]
                releases.append({
                    "repo": repo["name"],
                    "repo_url": repo["url"],
                    "description": repo["description"] or "",
                    "release": release_node["name"].replace(repo["name"], "").strip(),
                    "published_at": (release_node["publishedAt"] or "").split("T")[0],
                    "url": release_node["url"],
                })
        
        has_next_page = result["pageInfo"]["hasNextPage"]
        after_cursor = result["pageInfo"]["endCursor"]
    
    return releases

def fetch_tils(client: httpx.Client) -> List[str]:
    """Fetch top TILs from personal repo."""
    response = client.get("https://raw.githubusercontent.com/fulln/TIL/main/menu.json")
    response.raise_for_status()
    return response.json().get('top', [])

def fetch_blog_entries(client: httpx.Client) -> str:
    """Fetch recent blog posts from cnblogs."""
    response = client.get("https://www.cnblogs.com/wzqshb/ajax/sidecolumn.aspx")
    response.raise_for_status()
    # Use utf-8 for decoding
    soup = BeautifulSoup(response.text, 'html.parser')
    sidebar = soup.find(id="sidebar_recentposts")
    if sidebar and sidebar.ul:
        # Return the string representation of the ul element
        return str(sidebar.ul)
    return ""

def main():
    readme_path = root / "README.md"
    releases_path = root / "releases.md"
    
    # Initialize readme_contents to the current content
    readme_contents = readme_path.read_text(encoding="utf-8")

    with httpx.Client() as client:
        # 1. Fetch and process Releases
        if TOKEN:
            try:
                releases = fetch_releases(client, TOKEN)
                print(f"Total releases found: {len(releases)}")
                if releases:
                    releases.sort(key=lambda r: r["published_at"], reverse=True)
                    
                    # Update README
                    recent_releases_md = "\n".join([
                        f"* [{r['repo']} {r['release']}]({r['url']}) - {r['published_at']}"
                        for r in releases[:5]
                    ])
                    readme_contents = replace_chunk(readme_contents, "recent_releases", recent_releases_md)
                    print(f"Updated README with {len(releases[:5])} releases.")
                else:
                    print("No releases found in the GraphQL response.")
            except Exception as e:
                print(f"Error fetching releases: {e}")
        else:
            print("TOKEN not found, skipping releases update.")

        # 2. Fetch and update TILs
        try:
            tils = fetch_tils(client)
            print(f"Total TILs found: {len(tils)}")
            if tils:
                tils_md = "\n".join(tils)
                readme_contents = replace_chunk(readme_contents, "recent_TIL", tils_md)
        except Exception as e:
            print(f"Error fetching TILs: {e}")

        # 3. Fetch and update Blogs
        try:
            blog_entries = fetch_blog_entries(client)
            if blog_entries:
                readme_contents = replace_chunk(readme_contents, "recent_blogs", blog_entries)
        except Exception as e:
            print(f"Error fetching blogs: {e}")

        # Final save for README
        readme_path.write_text(readme_contents, encoding="utf-8")

if __name__ == "__main__":
    main()
