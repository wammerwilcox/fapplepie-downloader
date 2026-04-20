# yt-dlp Optimization Settings

## Current Optimizations

The script now uses the following yt-dlp arguments for faster downloads:

### Aria2c Integration

- `--external-downloader aria2c` - Uses aria2c instead of the default downloader for parallel downloads
- `--external-downloader-args '-x 16 -k 1M --max-connection-per-server=16 --split=16'`
  - `-x 16` - Use 16 parallel connections
  - `-k 1M` - 1MB chunk size
  - `--max-connection-per-server=16` - Maximum 16 connections per server
  - `--split=16` - Split file into 16 segments

### Fragment Handling

- `--concurrent-fragments 4` - Download up to 4 video fragments concurrently (for HLS/DASH streams)

### Performance

- `-q` (quiet mode) - Reduces terminal output verbosity, slightly improving performance

## Speed Improvements

These optimizations provide:

1. **Parallel downloads** - Up to 16 simultaneous connections per file
2. **Faster fragment downloads** - 4 concurrent fragments for adaptive streams
3. **Reduced I/O overhead** - Quiet mode minimizes output processing
4. **Smart chunking** - 1MB chunks allow efficient resumption if interrupted

## Requirements

- `aria2c` must be installed (`brew install aria2` on macOS)

## Example Performance

Before: ~2-5 MB/s (single connection)
After: ~10-50+ MB/s (depending on server and connection limits)

## Further Customization

If downloads are still slow:

1. Increase `-x` value (e.g., `-x 32`) for more connections
2. Decrease `-k` value (e.g., `-k 512K`) for smaller chunks
3. Add `--socket-timeout 30` for better timeout handling

Edit the `cmd` list in `download_videos()` function to adjust these values.
