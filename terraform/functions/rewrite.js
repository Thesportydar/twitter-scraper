// CloudFront Function to handle sub-directory index.html resolution
function handler(event) {
    var request = event.request;
    var uri = request.uri;

    // Check if the URI ends with a slash
    if (uri.endsWith('/')) {
        request.uri += 'index.html';
    }
    // Check if the URI does not contain a file extension
    else if (!uri.includes('.')) {
        request.uri += '/index.html';
    }

    return request;
}