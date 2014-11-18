//
// Copyright (c) 2014 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// ShaderVars.cpp:
//  Methods for GL variable types (varyings, uniforms, etc)
//

#include <GLSLANG/ShaderLang.h>

namespace sh
{

ShaderVariable::ShaderVariable()
    : type(0),
      precision(0),
      arraySize(0),
      staticUse(false)
{}

ShaderVariable::ShaderVariable(GLenum typeIn, unsigned int arraySizeIn)
    : type(typeIn),
      precision(0),
      arraySize(arraySizeIn),
      staticUse(false)
{}

ShaderVariable::~ShaderVariable()
{}

ShaderVariable::ShaderVariable(const ShaderVariable &other)
    : type(other.type),
      precision(other.precision),
      name(other.name),
      mappedName(other.mappedName),
      arraySize(other.arraySize),
      staticUse(other.staticUse)
{}

ShaderVariable &ShaderVariable::operator=(const ShaderVariable &other)
{
    type = other.type;
    precision = other.precision;
    name = other.name;
    mappedName = other.mappedName;
    arraySize = other.arraySize;
    staticUse = other.staticUse;
    return *this;
}

Uniform::Uniform()
{}

Uniform::~Uniform()
{}

Uniform::Uniform(const Uniform &other)
    : ShaderVariable(other),
      fields(other.fields)
{}

Uniform &Uniform::operator=(const Uniform &other)
{
    ShaderVariable::operator=(other);
    fields = other.fields;
    return *this;
}

Attribute::Attribute()
    : location(-1)
{}

Attribute::~Attribute()
{}

Attribute::Attribute(const Attribute &other)
    : ShaderVariable(other),
      location(other.location)
{}

Attribute &Attribute::operator=(const Attribute &other)
{
    ShaderVariable::operator=(other);
    location = other.location;
    return *this;
}

InterfaceBlockField::InterfaceBlockField()
    : isRowMajorMatrix(false)
{}

InterfaceBlockField::~InterfaceBlockField()
{}

InterfaceBlockField::InterfaceBlockField(const InterfaceBlockField &other)
    : ShaderVariable(other),
      isRowMajorMatrix(other.isRowMajorMatrix),
      fields(other.fields)
{}

InterfaceBlockField &InterfaceBlockField::operator=(const InterfaceBlockField &other)
{
    ShaderVariable::operator=(other);
    isRowMajorMatrix = other.isRowMajorMatrix;
    fields = other.fields;
    return *this;
}

Varying::Varying()
    : interpolation(INTERPOLATION_SMOOTH)
{}

Varying::~Varying()
{}

Varying::Varying(const Varying &other)
    : ShaderVariable(other),
      interpolation(other.interpolation),
      fields(other.fields),
      structName(other.structName)
{}

Varying &Varying::operator=(const Varying &other)
{
    ShaderVariable::operator=(other);
    interpolation = other.interpolation;
    fields = other.fields;
    structName = other.structName;
    return *this;
}

InterfaceBlock::InterfaceBlock()
    : arraySize(0),
      layout(BLOCKLAYOUT_PACKED),
      isRowMajorLayout(false),
      staticUse(false)
{}

InterfaceBlock::~InterfaceBlock()
{}

InterfaceBlock::InterfaceBlock(const InterfaceBlock &other)
    : name(other.name),
      mappedName(other.mappedName),
      arraySize(other.arraySize),
      layout(other.layout),
      isRowMajorLayout(other.isRowMajorLayout),
      staticUse(other.staticUse),
      fields(other.fields)
{}

InterfaceBlock &InterfaceBlock::operator=(const InterfaceBlock &other)
{
    name = other.name;
    mappedName = other.mappedName;
    arraySize = other.arraySize;
    layout = other.layout;
    isRowMajorLayout = other.isRowMajorLayout;
    staticUse = other.staticUse;
    fields = other.fields;
    return *this;
}

}
