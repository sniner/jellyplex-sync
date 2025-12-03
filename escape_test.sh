escape_json() {
    echo "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

PATH_VAR='/Cumflix/movies/My "Movie" (2025)'
ESCAPED=$(escape_json "$PATH_VAR")
echo "Original: $PATH_VAR"
echo "Escaped:  $ESCAPED"
