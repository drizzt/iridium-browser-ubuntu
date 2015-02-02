// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "content/public/browser/resource_request_details.h"
#include "content/public/test/browser_test_utils.h"
#include "content/public/test/content_browser_test.h"
#include "content/public/test/content_browser_test_utils.h"
#include "content/shell/browser/shell.h"
#include "net/dns/mock_host_resolver.h"
#include "net/test/embedded_test_server/embedded_test_server.h"

namespace content {

class NavigationObserver: public WebContentsObserver {
 public:
  explicit NavigationObserver(WebContents* web_contents)
      : WebContentsObserver(web_contents) {}
  ~NavigationObserver() override {}

  void DidCommitProvisionalLoadForFrame(
      RenderFrameHost* render_frame_host,
      const GURL& url,
      ui::PageTransition transition_type) override {
    navigation_url_ = url;
  }

  void DidGetRedirectForResourceRequest(
      RenderViewHost* render_view_host,
      const ResourceRedirectDetails& details) override {
    redirect_url_ = details.new_url;
  }

  const GURL& navigation_url() const {
    return navigation_url_;
  }

  const GURL& redirect_url() const {
    return redirect_url_;
  }

 private:
  GURL redirect_url_;
  GURL navigation_url_;

  DISALLOW_COPY_AND_ASSIGN(NavigationObserver);
};

class CrossSiteRedirectorBrowserTest : public ContentBrowserTest {
 public:
  CrossSiteRedirectorBrowserTest() {}
};

IN_PROC_BROWSER_TEST_F(CrossSiteRedirectorBrowserTest,
                       VerifyCrossSiteRedirectURL) {
  // Map all hosts to localhost and setup the EmbeddedTestServer for redirects.
  host_resolver()->AddRule("*", "127.0.0.1");
  ASSERT_TRUE(embedded_test_server()->InitializeAndWaitUntilReady());
  SetupCrossSiteRedirector(embedded_test_server());

  // Navigate to http://localhost:<port>/cross-site/foo.com/title2.html and
  // ensure that the redirector forwards the navigation to
  // http://foo.com:<port>/title2.html
  NavigationObserver observer(shell()->web_contents());
  NavigateToURL(
      shell(),
      embedded_test_server()->GetURL("/cross-site/foo.com/title2.html"));

  // The expectation is that the cross-site redirector will take the
  // hostname supplied in the URL and rewrite the URL. Build the
  // expected URL to ensure navigation was properly redirected.
  GURL::Replacements replace_host;
  std::string foo_com("foo.com");
  GURL expected_url(embedded_test_server()->GetURL("/title2.html"));
  replace_host.SetHostStr(foo_com);
  expected_url = expected_url.ReplaceComponents(replace_host);

  EXPECT_EQ(expected_url, observer.navigation_url());
  EXPECT_EQ(observer.redirect_url(), observer.navigation_url());
}

}  // namespace content