//
// Copyright (c) 2013 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//

// formatutils.h: Queries for GL image formats.

#ifndef LIBGLESV2_FORMATUTILS_H_
#define LIBGLESV2_FORMATUTILS_H_

#include "angle_gl.h"

#include "libGLESv2/Caps.h"
#include "libGLESv2/angletypes.h"

#include <cstddef>

typedef void (*MipGenerationFunction)(size_t sourceWidth, size_t sourceHeight, size_t sourceDepth,
                                      const uint8_t *sourceData, size_t sourceRowPitch, size_t sourceDepthPitch,
                                      uint8_t *destData, size_t destRowPitch, size_t destDepthPitch);

typedef void (*LoadImageFunction)(size_t width, size_t height, size_t depth,
                                  const uint8_t *input, size_t inputRowPitch, size_t inputDepthPitch,
                                  uint8_t *output, size_t outputRowPitch, size_t outputDepthPitch);

typedef void (*InitializeTextureDataFunction)(size_t width, size_t height, size_t depth,
                                              uint8_t *output, size_t outputRowPitch, size_t outputDepthPitch);

typedef void (*ColorReadFunction)(const void *source, void *dest);
typedef void (*ColorWriteFunction)(const void *source, void *dest);
typedef void (*ColorCopyFunction)(const void *source, void *dest);

typedef void (*VertexCopyFunction)(const void *input, size_t stride, size_t count, void *output);

namespace gl
{

struct FormatType
{
    FormatType();

    GLenum internalFormat;
    ColorWriteFunction colorWriteFunction;
};
const FormatType &GetFormatTypeInfo(GLenum format, GLenum type);

struct Type
{
    Type();

    GLuint bytes;
    bool specialInterpretation;
};
const Type &GetTypeInfo(GLenum type);

struct InternalFormat
{
    InternalFormat();

    GLuint redBits;
    GLuint greenBits;
    GLuint blueBits;

    GLuint luminanceBits;

    GLuint alphaBits;
    GLuint sharedBits;

    GLuint depthBits;
    GLuint stencilBits;

    GLuint pixelBytes;

    GLuint componentCount;

    bool compressed;
    GLuint compressedBlockWidth;
    GLuint compressedBlockHeight;

    GLenum format;
    GLenum type;

    GLenum componentType;
    GLenum colorEncoding;

    typedef bool (*SupportCheckFunction)(GLuint, const Extensions &);
    SupportCheckFunction textureSupport;
    SupportCheckFunction renderSupport;
    SupportCheckFunction filterSupport;

    GLuint computeRowPitch(GLenum type, GLsizei width, GLint alignment) const;
    GLuint computeDepthPitch(GLenum type, GLsizei width, GLsizei height, GLint alignment) const;
    GLuint computeBlockSize(GLenum type, GLsizei width, GLsizei height) const;
};
const InternalFormat &GetInternalFormatInfo(GLenum internalFormat);

GLenum GetSizedInternalFormat(GLenum internalFormat, GLenum type);

typedef std::set<GLenum> FormatSet;
const FormatSet &GetAllSizedInternalFormats();

}

#endif LIBGLESV2_FORMATUTILS_H_
