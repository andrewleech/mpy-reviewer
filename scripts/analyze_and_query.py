#!/usr/bin/env python3
"""
Analyze a PR and query for relevant past feedback.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"

def analyze_pr(pr_number):
    """Analyze a PR to extract characteristics."""
    conn = sqlite3.connect(DB_PATH)

    # Get PR metadata
    cursor = conn.execute(
        "SELECT number, title, changed_files, additions, deletions FROM prs WHERE number = ?",
        (pr_number,)
    )
    pr = cursor.fetchone()

    if not pr:
        print(f"PR #{pr_number} not found")
        return None

    # Get files changed from review comments
    cursor = conn.execute(
        "SELECT DISTINCT path FROM review_comments WHERE pr_number = ?",
        (pr_number,)
    )
    files = [row[0] for row in cursor.fetchall()]

    conn.close()

    # Analyze paths to extract components, ports, subsystems
    components = set()
    ports = set()
    subsystems = set()
    language_contexts = set()

    for file in files:
        parts = file.split('/')

        # Determine component
        if parts[0] == 'py':
            components.add('py_core')
        elif parts[0] == 'extmod':
            components.add('extmod')
        elif parts[0] == 'ports':
            components.add('port_specific')
            if len(parts) > 1:
                ports.add(parts[1])
        elif parts[0] == 'tools':
            components.add('tools')
        elif parts[0] == 'tests':
            components.add('tests')
        elif parts[0] == 'docs':
            components.add('docs')

        # Determine language
        if file.endswith('.py'):
            language_contexts.add('python_code')
        elif file.endswith(('.c', '.h')):
            language_contexts.add('c_code')
        elif file.endswith('.rst'):
            language_contexts.add('documentation')
        elif file.endswith('Makefile') or file.endswith('.mk'):
            language_contexts.add('makefile')

        # Extract subsystems from filenames
        filename = parts[-1]
        if 'bluetooth' in filename or 'bt' in filename:
            subsystems.add('bluetooth')
        if 'uart' in filename:
            subsystems.add('uart')
        if 'usb' in filename:
            subsystems.add('usb')
        if 'network' in filename:
            subsystems.add('networking')

    return {
        'number': pr[0],
        'title': pr[1],
        'changed_files': pr[2],
        'additions': pr[3],
        'deletions': pr[4],
        'files': files,
        'components': list(components),
        'ports': list(ports),
        'subsystems': list(subsystems),
        'language_contexts': list(language_contexts)
    }

def query_relevant_feedback(pr_analysis, limit=20):
    """Query for relevant past feedback based on PR characteristics."""
    conn = sqlite3.connect(DB_PATH)

    results = []

    # Query 1: Exact component match
    for component in pr_analysis['components']:
        cursor = conn.execute("""
            SELECT
                cc.comment_id,
                cc.comment_type,
                cc.domain_id,
                d.name as domain,
                cc.theme,
                cc.severity,
                cc.is_style_example,
                cc.component,
                cc.port,
                cc.subsystem,
                cc.concern_type,
                cc.feedback_type,
                cc.is_pattern,
                cc.has_code_suggestion,
                cc.keywords,
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.body
                    WHEN cc.comment_type = 'issue_comment' THEN ic.body
                END as body,
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.pr_number
                    WHEN cc.comment_type = 'issue_comment' THEN ic.pr_number
                END as pr_number
            FROM comment_categories cc
            LEFT JOIN domains d ON cc.domain_id = d.id
            LEFT JOIN review_comments rc ON cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
            LEFT JOIN issue_comments ic ON cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
            WHERE cc.component = ?
        """, (component,))

        for row in cursor.fetchall():
            results.append({
                'comment_id': row[0],
                'comment_type': row[1],
                'domain': row[3],
                'theme': row[4],
                'severity': row[5],
                'is_style_example': row[6],
                'component': row[7],
                'port': row[8],
                'subsystem': row[9],
                'concern_type': row[10],
                'feedback_type': row[11],
                'is_pattern': row[12],
                'has_code_suggestion': row[13],
                'keywords': json.loads(row[14]) if row[14] else [],
                'body': row[15],
                'pr_number': row[16],
                'relevance_score': 10,  # Exact component match
                'match_reason': f'Same component: {component}'
            })

    # Query 2: Language context match
    for lang in pr_analysis['language_contexts']:
        cursor = conn.execute("""
            SELECT
                cc.comment_id,
                cc.comment_type,
                d.name as domain,
                cc.theme,
                cc.severity,
                cc.is_style_example,
                cc.component,
                cc.language_context,
                cc.concern_type,
                cc.is_pattern,
                cc.keywords,
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.body
                    WHEN cc.comment_type = 'issue_comment' THEN ic.body
                END as body,
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.pr_number
                    WHEN cc.comment_type = 'issue_comment' THEN ic.pr_number
                END as pr_number
            FROM comment_categories cc
            LEFT JOIN domains d ON cc.domain_id = d.id
            LEFT JOIN review_comments rc ON cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
            LEFT JOIN issue_comments ic ON cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
            WHERE cc.language_context = ?
            AND cc.comment_id NOT IN ({})
        """.format(','.join(str(r['comment_id']) for r in results) if results else '0'), (lang,))

        for row in cursor.fetchall():
            results.append({
                'comment_id': row[0],
                'comment_type': row[1],
                'domain': row[2],
                'theme': row[3],
                'severity': row[4],
                'is_style_example': row[5],
                'component': row[6],
                'language_context': row[7],
                'concern_type': row[8],
                'is_pattern': row[9],
                'keywords': json.loads(row[10]) if row[10] else [],
                'body': row[11],
                'pr_number': row[12],
                'relevance_score': 5,  # Language match
                'match_reason': f'Same language: {lang}'
            })

    # Query 3: Patterns (always relevant)
    cursor = conn.execute("""
        SELECT
            cc.comment_id,
            cc.comment_type,
            d.name as domain,
            cc.theme,
            cc.severity,
            cc.is_style_example,
            cc.concern_type,
            cc.is_pattern,
            cc.keywords,
            CASE
                WHEN cc.comment_type = 'review_comment' THEN rc.body
                WHEN cc.comment_type = 'issue_comment' THEN ic.body
            END as body,
            CASE
                WHEN cc.comment_type = 'review_comment' THEN rc.pr_number
                WHEN cc.comment_type = 'issue_comment' THEN ic.pr_number
            END as pr_number
        FROM comment_categories cc
        LEFT JOIN domains d ON cc.domain_id = d.id
        LEFT JOIN review_comments rc ON cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
        LEFT JOIN issue_comments ic ON cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
        WHERE cc.is_pattern = 1
        AND cc.comment_id NOT IN ({})
    """.format(','.join(str(r['comment_id']) for r in results) if results else '0'))

    for row in cursor.fetchall():
        results.append({
            'comment_id': row[0],
            'comment_type': row[1],
            'domain': row[2],
            'theme': row[3],
            'severity': row[4],
            'is_style_example': row[5],
            'concern_type': row[6],
            'is_pattern': row[7],
            'keywords': json.loads(row[8]) if row[8] else [],
            'body': row[9],
            'pr_number': row[10],
            'relevance_score': 8,  # Patterns are generally useful
            'match_reason': 'Reusable pattern'
        })

    conn.close()

    # Sort by relevance
    results.sort(key=lambda x: x['relevance_score'], reverse=True)

    return results[:limit]

def main():
    pr_number = 18381

    print(f"Analyzing PR #{pr_number}...\n")
    analysis = analyze_pr(pr_number)

    if not analysis:
        return

    print(f"Title: {analysis['title']}")
    print(f"Changed files: {analysis['changed_files']}, +{analysis['additions']} -{analysis['deletions']}")
    print(f"\nFiles:")
    for f in analysis['files']:
        print(f"  - {f}")
    print(f"\nComponents: {', '.join(analysis['components'])}")
    print(f"Ports: {', '.join(analysis['ports']) if analysis['ports'] else 'none'}")
    print(f"Subsystems: {', '.join(analysis['subsystems']) if analysis['subsystems'] else 'none'}")
    print(f"Languages: {', '.join(analysis['language_contexts'])}")

    print(f"\n{'='*80}")
    print("Querying for relevant past feedback...\n")

    relevant = query_relevant_feedback(analysis)

    print(f"Found {len(relevant)} relevant comments:\n")

    for i, r in enumerate(relevant, 1):
        print(f"{i}. [{r['relevance_score']}] PR #{r['pr_number']} - {r['domain']}: {r['theme']}")
        print(f"   Match: {r['match_reason']}")
        print(f"   Pattern: {'Yes' if r.get('is_pattern') else 'No'}, "
              f"Style example: {'Yes' if r.get('is_style_example') else 'No'}")
        print(f"   Comment: {r['body'][:100]}")
        if len(r['body']) > 100:
            print("   ...")
        print()

if __name__ == "__main__":
    main()
