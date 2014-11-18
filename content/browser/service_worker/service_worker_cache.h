// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef CONTENT_BROWSER_SERVICE_WORKER_SERVICE_WORKER_CACHE_H_
#define CONTENT_BROWSER_SERVICE_WORKER_SERVICE_WORKER_CACHE_H_

#include "base/callback.h"
#include "base/files/file_path.h"
#include "base/memory/weak_ptr.h"

namespace net {
class URLRequestContext;
}

namespace webkit_blob {
class BlobStorageContext;
}

namespace content {

// TODO(jkarlin): Fill this in with a real Cache implementation as
// specified in
// https://slightlyoff.github.io/ServiceWorker/spec/service_worker/index.html.
// TODO(jkarlin): Unload cache backend from memory once the cache object is no
// longer referenced in javascript.

// Represents a ServiceWorker Cache as seen in
// https://slightlyoff.github.io/ServiceWorker/spec/service_worker/index.html.
// InitializeIfNeeded must be called before calling the other public members.
class ServiceWorkerCache {
 public:
  static scoped_ptr<ServiceWorkerCache> CreateMemoryCache(
      const std::string& name,
      net::URLRequestContext* request_context,
      base::WeakPtr<webkit_blob::BlobStorageContext> blob_context);
  static scoped_ptr<ServiceWorkerCache> CreatePersistentCache(
      const base::FilePath& path,
      const std::string& name,
      net::URLRequestContext* request_context,
      base::WeakPtr<webkit_blob::BlobStorageContext> blob_context);

  virtual ~ServiceWorkerCache();

  // Loads the backend and calls the callback with the result (true for
  // success). This must be called before member functions that require a
  // backend are called.
  void CreateBackend(const base::Callback<void(bool)>& callback);

  void set_name(const std::string& name) { name_ = name; }
  const std::string& name() const { return name_; }
  int32 id() const { return id_; }
  void set_id(int32 id) { id_ = id; }

  base::WeakPtr<ServiceWorkerCache> AsWeakPtr();

 private:
  ServiceWorkerCache(
      const base::FilePath& path,
      const std::string& name,
      net::URLRequestContext* request_context,
      base::WeakPtr<webkit_blob::BlobStorageContext> blob_context);

  base::FilePath path_;
  std::string name_;
  net::URLRequestContext* request_context_;
  base::WeakPtr<webkit_blob::BlobStorageContext> blob_storage_context_;
  int32 id_;

  base::WeakPtrFactory<ServiceWorkerCache> weak_ptr_factory_;

  DISALLOW_COPY_AND_ASSIGN(ServiceWorkerCache);
};

}  // namespace content

#endif  // CONTENT_BROWSER_SERVICE_WORKER_SERVICE_WORKER_CACHE_H_
