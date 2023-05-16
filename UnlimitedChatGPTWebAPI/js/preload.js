Object.defineProperties(navigator, {
    webdriver: {
        get: () => undefined
    }
});
const get_headers = (response) => {
    let headers = {}
    response.headers.forEach((value, key) => {
        headers[key] = value
    });
    return headers;
}
let fetchCounter = 0;

function trackedFetch(...args) {
    fetchCounter++;
    return fetch(...args)
        .catch((e) => {
            return new Response(JSON.stringify({
                code: 500,
                message: e.message
            }), {
                status: 500,
                headers: {
                    'Content-Type': 'application/json'
                }
            })
        })
}

function waitForNoFetch(timeout = 30000) {
    const noFetchPromise = new Promise(resolve => {
        const checkInterval = setInterval(() => {
            if (fetchCounter <= 0) {
                clearInterval(checkInterval);
                resolve();
            }
        }, 100);
    });

    const timeoutPromise = new Promise((_, reject) => {
        const timer = setTimeout(() => {
            clearTimeout(timer);
            reject(new Error('Timeout exceeded'));
        }, timeout);
    });

    return Promise.race([noFetchPromise, timeoutPromise]);
}
