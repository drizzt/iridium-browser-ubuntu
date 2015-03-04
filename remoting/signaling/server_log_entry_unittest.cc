// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "remoting/signaling/server_log_entry_unittest.h"

#include <sstream>

#include "testing/gtest/include/gtest/gtest.h"
#include "third_party/webrtc/libjingle/xmllite/xmlelement.h"

using buzz::QName;
using buzz::XmlAttr;
using buzz::XmlElement;

namespace remoting {

const char kJabberClientNamespace[] = "jabber:client";
const char kChromotingNamespace[] = "google:remoting";

XmlElement* GetLogElementFromStanza(XmlElement* stanza) {
  if (stanza->Name() != QName(kJabberClientNamespace, "iq")) {
    ADD_FAILURE() << "Expected element 'iq'";
    return NULL;
  }
  XmlElement* log_element = stanza->FirstChild()->AsElement();
  if (log_element->Name() != QName(kChromotingNamespace, "log")) {
    ADD_FAILURE() << "Expected element 'log'";
    return NULL;
  }
  if (log_element->NextChild()) {
    ADD_FAILURE() << "Expected only 1 child of 'iq'";
    return NULL;
  }
  return log_element;
}

XmlElement* GetSingleLogEntryFromStanza(XmlElement* stanza) {
  XmlElement* log_element = GetLogElementFromStanza(stanza);
  if (!log_element) {
    // Test failure already recorded, so just return NULL here.
    return NULL;
  }
  XmlElement* entry = log_element->FirstChild()->AsElement();
  if (entry->Name() != QName(kChromotingNamespace, "entry")) {
    ADD_FAILURE() << "Expected element 'entry'";
    return NULL;
  }
  if (entry->NextChild()) {
    ADD_FAILURE() << "Expected only 1 child of 'log'";
    return NULL;
  }
  return entry;
}

bool VerifyStanza(
    const std::map<std::string, std::string>& key_value_pairs,
    const std::set<std::string> keys,
    const XmlElement* elem,
    std::string* error) {
  int attrCount = 0;
  for (const XmlAttr* attr = elem->FirstAttr(); attr != NULL;
       attr = attr->NextAttr(), attrCount++) {
    if (attr->Name().Namespace().length() != 0) {
      *error = "attribute has non-empty namespace " +
          attr->Name().Namespace();
      return false;
    }
    const std::string& key = attr->Name().LocalPart();
    const std::string& value = attr->Value();
    std::map<std::string, std::string>::const_iterator iter =
        key_value_pairs.find(key);
    if (iter == key_value_pairs.end()) {
      if (keys.find(key) == keys.end()) {
        *error = "unexpected attribute " + key;
        return false;
      }
    } else {
      if (iter->second != value) {
        *error = "attribute " + key + " has value " + iter->second +
            ": expected " + value;
        return false;
      }
    }
  }
  int attr_count_expected = key_value_pairs.size() + keys.size();
  if (attrCount != attr_count_expected) {
    std::stringstream s;
    s << "stanza has " << attrCount << " keys: expected "
      << attr_count_expected;
    *error = s.str();
    return false;
  }
  return true;
}

}  // namespace remoting