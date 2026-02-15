<?php
/**
 * ------------------------------------------------------------------------
 *  Author : Ngonidzashe Jiji
 *  Enhanced version with multiple authentication methods
 *  Version: 1.4 - Advanced Authentication Support
 *  Date:    2025-01-27
 * ------------------------------------------------------------------------
 */
 
ini_set('display_errors', '0');
error_reporting(E_ALL);
 
set_time_limit(60);
header('Content-Type: application/json; charset=utf-8');
 
function debug_log($message) {
    if (isset($_GET['debug']) && $_GET['debug'] === '1') {
        error_log("[FETCH DEBUG] " . $message);
    }
}
 
function json_error($msg, $code = 400, $details = null) {
    http_response_code($code);
    $response = ['error' => $msg];
    if ($details && isset($_GET['debug'])) {
        $response['debug'] = $details;
    }
    echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    exit;
}
 
function getRandomUserAgent() {
    $userAgents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
    ];
    return $userAgents[array_rand($userAgents)];
}
 
function setupAuthentication($ch, $url) {
    // Method 1: Basic HTTP Authentication
    if (isset($_GET['auth_user']) && isset($_GET['auth_pass'])) {
        curl_setopt($ch, CURLOPT_HTTPAUTH, CURLAUTH_BASIC);
        curl_setopt($ch, CURLOPT_USERPWD, $_GET['auth_user'] . ':' . $_GET['auth_pass']);
        debug_log("Using Basic HTTP Authentication");
        return true;
    }
    
    // Method 2: Bearer Token Authentication
    if (isset($_GET['bearer_token'])) {
        $headers = curl_getinfo($ch, CURLINFO_HEADER_OUT);
        $headers = is_array($headers) ? $headers : [];
        $headers[] = 'Authorization: Bearer ' . $_GET['bearer_token'];
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        debug_log("Using Bearer Token Authentication");
        return true;
    }
    
    // Method 3: API Key in Header
    if (isset($_GET['api_key'])) {
        $headers = curl_getinfo($ch, CURLINFO_HEADER_OUT);
        $headers = is_array($headers) ? $headers : [];
        $keyName = $_GET['api_key_name'] ?? 'X-API-Key';
        $headers[] = $keyName . ': ' . $_GET['api_key'];
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        debug_log("Using API Key Authentication: $keyName");
        return true;
    }
    
    // Method 4: Session Cookie
    if (isset($_GET['session_cookie'])) {
        curl_setopt($ch, CURLOPT_COOKIE, $_GET['session_cookie']);
        debug_log("Using Session Cookie Authentication");
        return true;
    }
    
    // Method 5: Custom Headers
    if (isset($_GET['custom_headers'])) {
        $customHeaders = json_decode($_GET['custom_headers'], true);
        if (is_array($customHeaders)) {
            $headers = curl_getinfo($ch, CURLINFO_HEADER_OUT);
            $headers = is_array($headers) ? $headers : [];
            foreach ($customHeaders as $key => $value) {
                $headers[] = "$key: $value";
            }
            curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
            debug_log("Using Custom Headers Authentication");
            return true;
        }
    }
    
    return false;
}
 
function attemptLoginFlow($url) {
    // Try to detect and handle common login flows
    $parts = parse_url($url);
    $baseUrl = $parts['scheme'] . '://' . $parts['host'];
    
    // Common login endpoints to try
    $loginEndpoints = [
        '/login',
        '/signin',
        '/auth',
        '/authenticate',
        '/api/login',
        '/api/auth'
    ];
    
    foreach ($loginEndpoints as $endpoint) {
        $loginUrl = $baseUrl . $endpoint;
        debug_log("Checking login endpoint: $loginUrl");
        
        // Try to access login page
        $ch = curl_init();
        curl_setopt_array($ch, [
            CURLOPT_URL => $loginUrl,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_TIMEOUT => 10,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_SSL_VERIFYHOST => 0,
            CURLOPT_USERAGENT => getRandomUserAgent()
        ]);
        
        $result = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        
        if ($httpCode == 200 && !empty($result)) {
            debug_log("Found potential login endpoint: $loginUrl");
            return $loginUrl;
        }
    }
    
    return null;
}
 
function fetchWithAdvancedAuth($url, $maxRetries = 3) {
    $attempts = 0;
    $lastError = '';
    
    while ($attempts < $maxRetries) {
        $attempts++;
        debug_log("Attempt $attempts of $maxRetries");
        
        $parts = parse_url($url);
        $host = $parts['host'];
        $scheme = $parts['scheme'];
        
        // Create cookie jar
        $tempDir = sys_get_temp_dir();
        if (!is_writable($tempDir)) {
            $tempDir = dirname(__FILE__);
        }
        $cookieJar = $tempDir . '/fetch_cookie_' . md5($url . time() . $attempts) . '.txt';
        
        $ch = curl_init();
        if (!$ch) {
            $lastError = 'Failed to initialize cURL';
            continue;
        }
        
        // Basic cURL setup
        curl_setopt_array($ch, [
            CURLOPT_URL => $url,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS => 10,
            CURLOPT_CONNECTTIMEOUT => 20,
            CURLOPT_TIMEOUT => 60,
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_SSL_VERIFYHOST => 0,
            CURLOPT_ENCODING => '',
            CURLOPT_COOKIEJAR => $cookieJar,
            CURLOPT_COOKIEFILE => $cookieJar,
            CURLOPT_AUTOREFERER => true,
            CURLOPT_FAILONERROR => false,
            CURLOPT_HEADER => true, // Include headers in output
            CURLOPT_NOBODY => false
        ]);
        
        // Enhanced headers
        $ua = getRandomUserAgent();
        $headers = [
            "User-Agent: $ua",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language: en-US,en;q=0.9",
            "Accept-Encoding: gzip, deflate, br",
            "Connection: keep-alive",
            "Upgrade-Insecure-Requests: 1",
            "Cache-Control: no-cache",
            "Pragma: no-cache"
        ];
        
        // Add referer for subsequent attempts
        if ($attempts > 1) {
            $referer = $scheme . '://' . $host . '/';
            $headers[] = "Referer: $referer";
        }
        
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        
        // Setup authentication
        $authConfigured = setupAuthentication($ch, $url);
        
        // Special handling for first 401 - try without auth to see what's needed
        if ($attempts == 1 && !$authConfigured) {
            debug_log("First attempt without authentication to analyze requirements");
        }
        
        // Execute request
        debug_log("Executing cURL request (attempt $attempts)");
        $response = curl_exec($ch);
        $curlErr = curl_error($ch);
        $curlErrNo = curl_errno($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $contentType = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
        $effectiveUrl = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
        $headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
        
        debug_log("HTTP Code: $httpCode, Content-Type: $contentType");
        
        // Separate headers and body
        $headers_received = '';
        $body = '';
        if ($response !== false && $headerSize > 0) {
            $headers_received = substr($response, 0, $headerSize);
            $body = substr($response, $headerSize);
        }
        
        curl_close($ch);
        
        // Clean up cookie file
        if (file_exists($cookieJar)) {
            @unlink($cookieJar);
        }
        
        // Handle response
        if ($httpCode >= 200 && $httpCode < 300) {
            debug_log("Success on attempt $attempts");
            return [
                'success' => true,
                'html' => $body,
                'http_code' => $httpCode,
                'content_type' => $contentType,
                'effective_url' => $effectiveUrl,
                'attempts' => $attempts,
                'headers' => $headers_received
            ];
        } elseif ($httpCode == 401) {
            $lastError = "HTTP 401 Unauthorized";
            
            // Analyze WWW-Authenticate header for auth requirements
            if (preg_match('/WWW-Authenticate:\s*(.+)/i', $headers_received, $matches)) {
                $authHeader = trim($matches[1]);
                debug_log("WWW-Authenticate header: $authHeader");
                $lastError .= " - Auth method required: $authHeader";
            }
            
            // If no auth was configured and this is first attempt, suggest auth methods
            if (!$authConfigured && $attempts == 1) {
                $lastError .= " - No authentication provided";
            }
            
            // Don't retry if we already tried with auth
            if ($authConfigured) {
                break;
            }
        } elseif ($httpCode == 403) {
            $lastError = "HTTP 403 Forbidden - Access denied";
            if ($attempts < $maxRetries) {
                sleep(rand(2, 5));
                continue;
            }
        } else {
            $lastError = "HTTP Error $httpCode";
            if ($attempts < $maxRetries && $httpCode >= 500) {
                continue; // Retry server errors
            }
        }
        
        debug_log("Attempt $attempts failed: $lastError");
        
        // Add delay between attempts
        if ($attempts < $maxRetries) {
            sleep(rand(1, 3));
        }
    }
    
    return [
        'success' => false,
        'error' => $lastError,
        'attempts' => $attempts
    ];
}
 
function extractMeaningfulContent($html) {
    if (empty($html)) {
        return ['title' => '', 'content' => ''];
    }
    
    // Remove scripts, styles, etc.
    $html = preg_replace('/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/mi', '', $html);
    $html = preg_replace('/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/mi', '', $html);
    $html = preg_replace('/<!--.*?-->/s', '', $html);
    
    // Extract title
    $title = '';
    if (preg_match('/<title[^>]*>(.*?)<\/title>/is', $html, $matches)) {
        $title = html_entity_decode(trim(strip_tags($matches[1])), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    }
    
    // Extract content
    $contentParts = [];
    $patterns = [
        '/<main[^>]*>(.*?)<\/main>/is',
        '/<article[^>]*>(.*?)<\/article>/is',
        '/<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)<\/div>/is',
        '/<section[^>]*>(.*?)<\/section>/is',
        '/<p[^>]*>(.*?)<\/p>/is'
    ];
    
    foreach ($patterns as $pattern) {
        if (preg_match_all($pattern, $html, $matches)) {
            $contentParts = array_merge($contentParts, $matches[1]);
            if (count($contentParts) > 0) break;
        }
    }
    
    $meaningfulContent = [];
    foreach ($contentParts as $part) {
        $text = strip_tags($part);
        $text = html_entity_decode($text, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $text = preg_replace('/\s+/', ' ', trim($text));
        
        if (strlen($text) > 20) {
            $meaningfulContent[] = $text;
        }
    }
    
    $content = implode("\n\n", array_unique($meaningfulContent));
    
    return [
        'title' => $title,
        'content' => trim($content)
    ];
}
 
// Validation
if (!isset($_GET['url']) || trim($_GET['url']) === '') {
    json_error('Missing url parameter. 
 
Usage Examples:
- Basic: ?url=https://example.com
- Basic Auth: ?url=URL&auth_user=username&auth_pass=password  
- Bearer Token: ?url=URL&bearer_token=your_token
- API Key: ?url=URL&api_key=your_key&api_key_name=X-API-Key
- Session Cookie: ?url=URL&session_cookie=session_id=abc123
- Custom Headers: ?url=URL&custom_headers={"Authorization":"Bearer token","X-Custom":"value"}', 400);
}
 
$url = trim($_GET['url']);
debug_log("Processing URL: " . $url);
 
if (!filter_var($url, FILTER_VALIDATE_URL)) {
    json_error('Invalid URL format.', 400);
}
 
$parts = parse_url($url);
if (!isset($parts['scheme']) || !in_array(strtolower($parts['scheme']), ['http', 'https'], true)) {
    json_error('Only http and https URLs are allowed.', 400);
}
 
// Fetch with advanced authentication
$fetchResult = fetchWithAdvancedAuth($url, 3);
 
if (!$fetchResult['success']) {
    $errorMsg = $fetchResult['error'];
    $suggestions = [];
    
    if (strpos($errorMsg, '401') !== false) {
        $suggestions[] = "Authentication required. Try one of these methods:";
        $suggestions[] = "• Basic Auth: add &auth_user=username&auth_pass=password";
        $suggestions[] = "• Bearer Token: add &bearer_token=your_token";
        $suggestions[] = "• API Key: add &api_key=your_key";
        $suggestions[] = "• Session Cookie: add &session_cookie=name=value";
        $suggestions[] = "• Custom Headers: add &custom_headers={\"Authorization\":\"Bearer token\"}";
        
        // Try to detect login page
        $loginUrl = attemptLoginFlow($url);
        if ($loginUrl) {
            $suggestions[] = "• Detected possible login endpoint: $loginUrl";
        }
    }
    
    json_error($errorMsg, 401, [
        'attempts' => $fetchResult['attempts'],
        'suggestions' => $suggestions,
        'auth_methods_available' => [
            'basic_auth' => 'auth_user & auth_pass parameters',
            'bearer_token' => 'bearer_token parameter', 
            'api_key' => 'api_key & api_key_name parameters',
            'session_cookie' => 'session_cookie parameter',
            'custom_headers' => 'custom_headers parameter (JSON)'
        ]
    ]);
}
 
$html = $fetchResult['html'];
 
if (empty($html)) {
    json_error('No content received from URL', 502);
}
 
// Extract content
try {
    $extracted = extractMeaningfulContent($html);
    
    $response = [
        'success' => true,
        'title' => $extracted['title'],
        'content' => $extracted['content'],
        'http_status' => $fetchResult['http_code'],
        'url' => $url,
        'effective_url' => $fetchResult['effective_url'],
        'content_length' => strlen($extracted['content']),
        'attempts' => $fetchResult['attempts']
    ];
    
    if (isset($_GET['debug'])) {
        $response['debug'] = [
            'original_html_length' => strlen($html),
            'headers_received' => $fetchResult['headers'] ?? '',
            'fetch_result' => $fetchResult
        ];
    }
    
    echo json_encode($response, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    
} catch (Exception $e) {
    json_error('Failed to extract content: ' . $e->getMessage(), 500);
}
?>