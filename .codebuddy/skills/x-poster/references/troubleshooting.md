# x-poster Troubleshooting Guide

## Common Issues and Solutions

### Chrome Won't Start

**Symptom**: Error about Chrome not found or debug port not ready.

**Solutions**:
1. Verify Chrome is installed: `ls /Applications/Google\ Chrome.app`
2. Specify Chrome path explicitly: `xpost --chrome-path /path/to/chrome <command>`
3. Kill leftover Chrome instances: `pkill -f "chrome.*remote-debugging-port"`

### Login Required

**Symptom**: Command hangs at "Login required" message.

**Solution**: The tool launches a Chrome window. Manually log in to X in that window. The session persists in the profile directory for future runs.

### Paste Not Working (macOS)

**Symptom**: Images or text not pasting into X editor.

**Solutions**:
1. Grant Accessibility permissions: **System Settings → Privacy & Security → Accessibility** → Add terminal app
2. Run `xpost check` to verify permissions
3. Ensure no other app is intercepting clipboard

### Article Command Fails

**Symptom**: Long-form article editor not available.

**Solution**: X Articles require X Premium subscription. Verify your account has Premium access.

### Timeout Errors

**Symptom**: "Selector not found after Xs" errors.

**Solutions**:
1. X may be slow — increase wait by running with `-v` to see timing
2. Page structure may have changed — X updates DOM frequently
3. Network issues — ensure stable internet connection

### Port Conflicts

**Symptom**: Chrome CDP port already in use.

**Solution**:
```bash
# Find and kill processes using CDP ports
lsof -i :9222-9300 | grep Chrome
pkill -f "chrome.*remote-debugging-port"
```

### Video Upload Stalls

**Symptom**: Video upload progress stuck.

**Solutions**:
1. Check video format (MP4/MOV/WebM supported)
2. Check file size (X limit varies by account type)
3. Wait longer — large videos may take up to 180 seconds

### Shell Special Characters

**Symptom**: `dquote>` prompt when using `!` in text.

**Solution**: Use single quotes instead of double quotes in zsh:
```bash
# Wrong
xpost post "Hello world!"
# Correct
xpost post 'Hello world!'
```

### Views Count Shows Wrong Number

**Symptom**: Views metric shows truncated number.

**Note**: The tool automatically handles localized number formats (e.g., "282.7万", "1.2M", "3.5K") and converts them to full numbers. If you see an issue, it may be due to X UI changes. Report the raw output with `--json` flag for debugging.

## Environment Requirements

| Requirement | Minimum | Notes |
|------------|---------|-------|
| OS | macOS | Uses macOS-specific clipboard and keystroke APIs |
| Python | 3.9+ | Tested on 3.11 |
| Chrome | Any recent | Chrome, Chromium, Edge, or Brave |
| Accessibility | Granted | Required for image pasting via keystroke simulation |

## X DOM Selectors

These are the CSS selectors used to interact with X's interface. If X updates its UI, these may need to be updated:

| Purpose | Selector |
|---------|----------|
| Tweet article | `article[data-testid="tweet"]` |
| Tweet text | `[data-testid="tweetText"]` |
| User name | `[data-testid="User-Name"]` |
| Reply button | `[data-testid="reply"]` |
| Retweet button | `[data-testid="retweet"]` |
| Like button | `[data-testid="like"]` or `[data-testid="unlike"]` |
| Views link | `a[href*="/analytics"]` |
| Tweet photo | `[data-testid="tweetPhoto"] img` |
| Login indicator | `[data-testid="loginButton"], [href="/login"]` |
| Post button | `[data-testid="tweetButton"], [data-testid="tweetButtonInline"]` |
| Tweet editor | `[data-testid="tweetTextarea_0"]` |
| Quoted tweet | `[data-testid="quoteTweet"]` |
