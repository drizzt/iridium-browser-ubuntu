//
// Copyright (c) 2002-2013 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//

// Texture.h: Defines the abstract gl::Texture class and its concrete derived
// classes Texture2D and TextureCubeMap. Implements GL texture objects and
// related functionality. [OpenGL ES 2.0.24] section 3.7 page 63.

#ifndef LIBANGLE_TEXTURE_H_
#define LIBANGLE_TEXTURE_H_

#include "common/debug.h"
#include "libANGLE/RefCountObject.h"
#include "libANGLE/angletypes.h"
#include "libANGLE/Constants.h"
#include "libANGLE/renderer/TextureImpl.h"
#include "libANGLE/Caps.h"

#include "angle_gl.h"

#include <vector>

namespace egl
{
class Surface;
}

namespace rx
{
class TextureStorageInterface;
class Image;
}

namespace gl
{
class Framebuffer;
class FramebufferAttachment;
struct ImageIndex;
struct Data;

bool IsMipmapFiltered(const gl::SamplerState &samplerState);

class Texture : public RefCountObject
{
  public:
    Texture(rx::TextureImpl *impl, GLuint id, GLenum target);

    virtual ~Texture();

    GLenum getTarget() const;

    const SamplerState &getSamplerState() const { return mSamplerState; }
    SamplerState &getSamplerState() { return mSamplerState; }

    void setUsage(GLenum usage);
    GLenum getUsage() const;

    GLint getBaseLevelWidth() const;
    GLint getBaseLevelHeight() const;
    GLint getBaseLevelDepth() const;
    GLenum getBaseLevelInternalFormat() const;

    GLsizei getWidth(const ImageIndex &index) const;
    GLsizei getHeight(const ImageIndex &index) const;
    GLenum getInternalFormat(const ImageIndex &index) const;

    virtual bool isSamplerComplete(const SamplerState &samplerState, const Data &data) const = 0;

    virtual Error setImage(GLenum target, size_t level, GLenum internalFormat, const Extents &size, GLenum format, GLenum type,
                           const PixelUnpackState &unpack, const uint8_t *pixels);
    virtual Error setSubImage(GLenum target, size_t level, const Box &area, GLenum format, GLenum type,
                              const PixelUnpackState &unpack, const uint8_t *pixels);

    virtual Error setCompressedImage(GLenum target, size_t level, GLenum internalFormat, const Extents &size,
                                     const PixelUnpackState &unpack, const uint8_t *pixels);
    virtual Error setCompressedSubImage(GLenum target, size_t level, const Box &area, GLenum format,
                                        const PixelUnpackState &unpack, const uint8_t *pixels);

    virtual Error copyImage(GLenum target, size_t level, const Rectangle &sourceArea, GLenum internalFormat,
                            const Framebuffer *source);
    virtual Error copySubImage(GLenum target, size_t level, const Offset &destOffset, const Rectangle &sourceArea,
                              const Framebuffer *source);

    virtual Error setStorage(GLenum target, size_t levels, GLenum internalFormat, const Extents &size);

    virtual Error generateMipmaps();

    // Texture serials provide a unique way of identifying a Texture that isn't a raw pointer.
    // "id" is not good enough, as Textures can be deleted, then re-allocated with the same id.
    unsigned int getTextureSerial() const;

    bool isImmutable() const;
    GLsizei immutableLevelCount();

    rx::TextureImpl *getImplementation() { return mTexture; }
    const rx::TextureImpl *getImplementation() const { return mTexture; }

    static const GLuint INCOMPLETE_TEXTURE_ID = static_cast<GLuint>(-1);   // Every texture takes an id at creation time. The value is arbitrary because it is never registered with the resource manager.

  protected:
    int mipLevels() const;
    const rx::Image *getBaseLevelImage() const;
    static unsigned int issueTextureSerial();

    rx::TextureImpl *mTexture;

    SamplerState mSamplerState;
    GLenum mUsage;

    GLsizei mImmutableLevelCount;

    GLenum mTarget;

    const unsigned int mTextureSerial;
    static unsigned int mCurrentTextureSerial;

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture);
};

class Texture2D : public Texture
{
  public:
    Texture2D(rx::TextureImpl *impl, GLuint id);

    virtual ~Texture2D();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    Error setImage(GLenum target, size_t level, GLenum internalFormat, const Extents &size, GLenum format, GLenum type,
                   const PixelUnpackState &unpack, const uint8_t *pixels) override;

    Error setCompressedImage(GLenum target, size_t level, GLenum internalFormat, const Extents &size,
                             const PixelUnpackState &unpack, const uint8_t *pixels) override;

    Error copyImage(GLenum target, size_t level, const Rectangle &sourceArea, GLenum internalFormat,
                    const Framebuffer *source) override;

    Error setStorage(GLenum target, size_t levels, GLenum internalFormat, const Extents &size) override;

    Error generateMipmaps() override;

    virtual bool isSamplerComplete(const SamplerState &samplerState, const Data &data) const;
    virtual void bindTexImage(egl::Surface *surface);
    virtual void releaseTexImage();

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture2D);

    bool isMipmapComplete() const;
    bool isLevelComplete(int level) const;

    egl::Surface *mSurface;
};

class TextureCubeMap : public Texture
{
  public:
    TextureCubeMap(rx::TextureImpl *impl, GLuint id);

    virtual ~TextureCubeMap();

    GLsizei getWidth(GLenum target, GLint level) const;
    GLsizei getHeight(GLenum target, GLint level) const;
    GLenum getInternalFormat(GLenum target, GLint level) const;
    bool isCompressed(GLenum target, GLint level) const;
    bool isDepth(GLenum target, GLint level) const;

    virtual bool isSamplerComplete(const SamplerState &samplerState, const Data &data) const;

    bool isCubeComplete() const;

    static int targetToLayerIndex(GLenum target);
    static GLenum layerIndexToTarget(GLint layer);

  private:
    DISALLOW_COPY_AND_ASSIGN(TextureCubeMap);

    bool isMipmapComplete() const;
    bool isFaceLevelComplete(int faceIndex, int level) const;
};

class Texture3D : public Texture
{
  public:
    Texture3D(rx::TextureImpl *impl, GLuint id);

    virtual ~Texture3D();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLsizei getDepth(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    virtual bool isSamplerComplete(const SamplerState &samplerState, const Data &data) const;

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture3D);

    bool isMipmapComplete() const;
    bool isLevelComplete(int level) const;
};

class Texture2DArray : public Texture
{
  public:
    Texture2DArray(rx::TextureImpl *impl, GLuint id);

    virtual ~Texture2DArray();

    GLsizei getWidth(GLint level) const;
    GLsizei getHeight(GLint level) const;
    GLsizei getLayers(GLint level) const;
    GLenum getInternalFormat(GLint level) const;
    bool isCompressed(GLint level) const;
    bool isDepth(GLint level) const;

    virtual bool isSamplerComplete(const SamplerState &samplerState, const Data &data) const;

  private:
    DISALLOW_COPY_AND_ASSIGN(Texture2DArray);

    bool isMipmapComplete() const;
    bool isLevelComplete(int level) const;
};

}

#endif   // LIBANGLE_TEXTURE_H_
