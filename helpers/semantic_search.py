"""
Optional: Semantic search using sentence-transformers
Only use if you want maximum accuracy and have installed: pip install sentence-transformers
"""

import os
import json
import logging
import numpy as np
import subprocess
from pathlib import Path
from sentence_transformers import SentenceTransformer, util

logger = logging.getLogger(__name__)

# Global model (loaded once)
_model = None

def get_model():
    """Lazy load the embedding model"""
    global _model
    if _model is None:
        # Small, fast model (80MB)
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


def get_current_commit_hash(repo_path: str) -> str:
    """Get current git commit hash for cache invalidation"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except:
        return "unknown"


def get_cached_embeddings(repo_path: str):
    """Load cached embeddings if available and valid"""
    cache_dir = os.path.join(repo_path, ".embeddings_cache")
    metadata_file = os.path.join(cache_dir, "metadata.json")
    embeddings_file = os.path.join(cache_dir, "embeddings.npy")
    file_paths_file = os.path.join(cache_dir, "file_paths.json")
    
    # Check if cache exists
    if not all(os.path.exists(f) for f in [metadata_file, embeddings_file, file_paths_file]):
        return None
    
    # Load metadata
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    # Check if cache is still valid (same commit)
    current_commit = get_current_commit_hash(repo_path)
    if metadata.get('commit_hash') != current_commit:
        logger.debug("[Cache] Repo changed, invalidating cache")
        return None
    
    # Load cached data
    embeddings = np.load(embeddings_file)
    with open(file_paths_file, 'r') as f:
        file_paths = json.load(f)
    
    logger.debug(f"[Cache] Loaded {len(file_paths)} cached embeddings")
    return file_paths, embeddings


def save_cached_embeddings(repo_path: str, file_paths: list, embeddings: np.ndarray):
    """Save embeddings to cache"""
    cache_dir = os.path.join(repo_path, ".embeddings_cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    # Save metadata
    metadata = {
        'commit_hash': get_current_commit_hash(repo_path),
        'timestamp': str(np.datetime64('now')),
        'file_count': len(file_paths)
    }
    with open(os.path.join(cache_dir, "metadata.json"), 'w') as f:
        json.dump(metadata, f)
    
    # Save embeddings
    np.save(os.path.join(cache_dir, "embeddings.npy"), embeddings)
    
    # Save file paths
    with open(os.path.join(cache_dir, "file_paths.json"), 'w') as f:
        json.dump(file_paths, f)
    
    logger.debug(f"[Cache] Saved {len(file_paths)} embeddings to cache")


def find_relevant_files_semantic(repo_path: str, spec: str, max_files: int = 5) -> list:
    """Find files using semantic similarity with caching"""
    
    model = get_model()
    
    # Try to load from cache first
    cached_data = get_cached_embeddings(repo_path)
    
    if cached_data:
        # Use cached embeddings
        file_paths, file_embeddings = cached_data
    else:
        # Build new embeddings
        relevant_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', 
                              '.css', '.scss', '.vue', '.svelte']
        
        # Collect all candidate files
        file_data = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build', '.embeddings_cache']]
            
            for file in files:
                if any(file.endswith(ext) for ext in relevant_extensions):
                    rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                    # Create searchable text from file path
                    searchable = rel_path.replace('/', ' ').replace('_', ' ').replace('-', ' ')
                    file_data.append((rel_path, searchable))
        
        if not file_data:
            return []
        
        # Encode file paths
        file_paths = [path for path, _ in file_data]
        file_texts = [text for _, text in file_data]
        
        logger.info(f"[Semantic] Encoding {len(file_paths)} files...")
        file_embeddings = model.encode(file_texts, convert_to_tensor=True)
        
        # Cache for next time
        save_cached_embeddings(repo_path, file_paths, file_embeddings.cpu().numpy())
    
    # Encode spec (always fresh, changes per ticket)
    spec_embedding = model.encode(spec, convert_to_tensor=True)
    
    # Calculate cosine similarity
    similarities = util.cos_sim(spec_embedding, file_embeddings)[0]
    
    # Get top N files
    top_indices = similarities.argsort(descending=True)[:max_files]
    
    return [file_paths[idx] for idx in top_indices]


# Hybrid: Combine keyword scoring + semantic search
def find_relevant_files_hybrid(repo_path: str, spec: str, max_files: int = 5) -> list:
    """Best of both worlds: keyword + semantic"""
    
    from helpers.workspace import calculate_relevance_score
    
    model = get_model()
    relevant_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', 
                          '.css', '.scss', '.vue', '.svelte']
    
    spec_lower = spec.lower()
    candidates = []
    
    # Collect candidates
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build']]
        
        for file in files:
            if any(file.endswith(ext) for ext in relevant_extensions):
                rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                full_path = os.path.join(root, file)
                candidates.append((rel_path, full_path))
    
    if not candidates:
        return []
    
    # Get semantic scores
    spec_embedding = model.encode(spec, convert_to_tensor=True)
    file_texts = [path.replace('/', ' ').replace('_', ' ') for path, _ in candidates]
    file_embeddings = model.encode(file_texts, convert_to_tensor=True)
    similarities = util.cos_sim(spec_embedding, file_embeddings)[0]
    
    # Combine with keyword scores
    scored_files = []
    for idx, (rel_path, full_path) in enumerate(candidates):
        keyword_score = calculate_relevance_score(rel_path, spec_lower, full_path)
        semantic_score = float(similarities[idx]) * 20  # Scale to ~20 range
        total_score = keyword_score + semantic_score
        scored_files.append((rel_path, total_score))
    
    # Sort and return top N
    scored_files.sort(key=lambda x: x[1], reverse=True)
    return [path for path, score in scored_files[:max_files]]
